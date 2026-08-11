from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.domain_modules.farm.domain import (
    CYCLE_TRANSITIONS,
    PRODUCT_TRANSITIONS,
    SUBMISSION_TRANSITIONS,
    TEMPLATE_TRANSITIONS,
    CycleStatus,
    FarmDomainError,
    ParticipationMode,
    ProductStatus,
    SubmissionStatus,
    TemplateStatus,
    TicketStatus,
    calculate_progress,
    ensure_transition,
    normalize_name,
    normalize_quantity,
)
from app.domain_modules.farm.models import (
    FarmCycle,
    FarmCycleGoal,
    FarmCycleParticipant,
    FarmCycleTicket,
    FarmProduct,
    FarmProof,
    FarmReview,
    FarmSubmission,
    FarmSubmissionItem,
    FarmTemplate,
    FarmTemplateItem,
)
from app.domain_modules.farm.schemas import (
    CycleCreate,
    ProductCreate,
    ReviewCreate,
    SubmissionCreate,
    TemplateCreate,
)
from app.platform.audit import write_audit
from app.platform.models import AutomationTask, DeliveryOutbox, ModuleConfigVersion, ModuleInstance, WorkState


def _conflict(expected: int, current: int) -> HTTPException:
    return HTTPException(status_code=409, detail={"message": "Revisao divergente.", "expected": expected, "current": current})


async def _owned(session: AsyncSession, model, guild_id: str, resource_id: int, *, lock: bool = False):
    query = select(model).where(model.id == resource_id, model.guild_id == guild_id)
    if lock:
        query = query.with_for_update()
    item = (await session.execute(query)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Recurso de Farm nao encontrado.")
    return item


async def _audit(session: AsyncSession, *, guild_id: str, actor_id: str | None, action: str, resource_type: str, resource_id: int, correlation_id: str, before: dict | None = None, after: dict | None = None) -> None:
    await write_audit(
        session,
        guild_id=guild_id,
        module_key="farm",
        actor_id=actor_id,
        actor_type="user" if actor_id else "system",
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        correlation_id=correlation_id,
        before=before,
        after=after,
    )


async def _published_config(session: AsyncSession, guild_id: str) -> dict[str, Any]:
    query = (
        select(ModuleConfigVersion.data)
        .join(ModuleInstance, ModuleInstance.published_config_version_id == ModuleConfigVersion.id)
        .where(
            ModuleInstance.guild_id == guild_id,
            ModuleInstance.module_key == "farm",
            ModuleConfigVersion.guild_id == guild_id,
            ModuleConfigVersion.module_key == "farm",
        )
    )
    return dict((await session.execute(query)).scalar_one_or_none() or {})


async def _enqueue(
    session: AsyncSession,
    *,
    guild_id: str,
    renderer_key: str,
    destination_id: str | None,
    resource_type: str,
    resource_id: int,
    payload: dict[str, Any],
    idempotency_key: str,
    correlation_id: str,
) -> None:
    if not destination_id:
        return
    existing = await session.scalar(
        select(DeliveryOutbox.id).where(
            DeliveryOutbox.guild_id == guild_id,
            DeliveryOutbox.module_key == "farm",
            DeliveryOutbox.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return
    session.add(
        DeliveryOutbox(
            guild_id=guild_id,
            module_key="farm",
            renderer_key=renderer_key,
            destination_type="channel",
            destination_id=destination_id,
            resource_type=resource_type,
            resource_id=str(resource_id),
            payload=payload,
            available_at=datetime.now(timezone.utc),
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            max_attempts=5,
        )
    )


async def list_products(session: AsyncSession, guild_id: str) -> list[FarmProduct]:
    return list((await session.execute(select(FarmProduct).where(FarmProduct.guild_id == guild_id).order_by(FarmProduct.status, FarmProduct.name))).scalars())


async def create_product(session: AsyncSession, *, guild_id: str, actor_id: str, correlation_id: str, data: ProductCreate) -> FarmProduct:
    normalized = normalize_name(data.name)
    existing = (await session.execute(select(FarmProduct.id).where(FarmProduct.guild_id == guild_id, FarmProduct.active_key == normalized))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Ja existe produto ativo com este nome.")
    item = FarmProduct(
        guild_id=guild_id,
        name=data.name,
        normalized_name=normalized,
        active_key=normalized,
        description=data.description,
        unit=data.unit,
        precision=data.precision,
        created_by=actor_id,
    )
    session.add(item)
    await session.flush()
    await _audit(session, guild_id=guild_id, actor_id=actor_id, action="farm.product.created", resource_type="farm_product", resource_id=item.id, correlation_id=correlation_id, after={"name": item.name, "unit": item.unit, "precision": item.precision})
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Produto ativo duplicado.") from exc
    return item


async def archive_product(session: AsyncSession, *, guild_id: str, product_id: int, expected_revision: int, actor_id: str, correlation_id: str) -> FarmProduct:
    item = await _owned(session, FarmProduct, guild_id, product_id, lock=True)
    if item.revision != expected_revision:
        raise _conflict(expected_revision, item.revision)
    try:
        ensure_transition(item.status, ProductStatus.archived, PRODUCT_TRANSITIONS)
    except FarmDomainError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    before = {"status": item.status, "revision": item.revision}
    item.status = ProductStatus.archived
    item.active_key = None
    item.archived_by = actor_id
    item.archived_at = datetime.now(timezone.utc)
    item.revision += 1
    await _audit(session, guild_id=guild_id, actor_id=actor_id, action="farm.product.archived", resource_type="farm_product", resource_id=item.id, correlation_id=correlation_id, before=before, after={"status": item.status, "revision": item.revision})
    await session.commit()
    return item


async def list_templates(session: AsyncSession, guild_id: str) -> list[FarmTemplate]:
    query = select(FarmTemplate).where(FarmTemplate.guild_id == guild_id).options(selectinload(FarmTemplate.items)).order_by(FarmTemplate.name, FarmTemplate.version.desc())
    return list((await session.execute(query)).scalars().unique())


async def create_template(session: AsyncSession, *, guild_id: str, actor_id: str, correlation_id: str, data: TemplateCreate, source_template_id: int | None = None) -> FarmTemplate:
    product_ids = [item.product_id for item in data.items]
    products = list((await session.execute(select(FarmProduct).where(FarmProduct.guild_id == guild_id, FarmProduct.id.in_(product_ids), FarmProduct.status == ProductStatus.active))).scalars())
    by_id = {item.id: item for item in products}
    if set(by_id) != set(product_ids):
        raise HTTPException(status_code=422, detail="Template referencia produto inexistente ou arquivado.")
    template_key = None
    version = 1
    if source_template_id is not None:
        source = await _owned(session, FarmTemplate, guild_id, source_template_id)
        template_key = source.template_key
        version = int(
            await session.scalar(
                select(func.max(FarmTemplate.version)).where(
                    FarmTemplate.guild_id == guild_id,
                    FarmTemplate.template_key == template_key,
                )
            )
            or 0
        ) + 1
    template = FarmTemplate(guild_id=guild_id, template_key=template_key or str(uuid4()), version=version, name=data.name, description=data.description, created_by=actor_id)
    session.add(template)
    await session.flush()
    for position, requested in enumerate(data.items):
        product = by_id[requested.product_id]
        try:
            quantity = normalize_quantity(requested.quantity, product.precision)
        except FarmDomainError as exc:
            raise HTTPException(status_code=422, detail=f"{product.name}: {exc}") from exc
        template.items.append(FarmTemplateItem(guild_id=guild_id, product_id=product.id, quantity=quantity, position=position))
    await _audit(session, guild_id=guild_id, actor_id=actor_id, action="farm.template.created", resource_type="farm_template", resource_id=template.id, correlation_id=correlation_id, after={"name": template.name, "items": len(template.items)})
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Versao de template criada concorrentemente; atualize a Central.") from exc
    return template


async def archive_template(session: AsyncSession, *, guild_id: str, template_id: int, expected_revision: int, actor_id: str, correlation_id: str) -> FarmTemplate:
    query = select(FarmTemplate).where(FarmTemplate.id == template_id, FarmTemplate.guild_id == guild_id).options(selectinload(FarmTemplate.items)).with_for_update()
    item = (await session.execute(query)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Template nao encontrado.")
    if item.revision != expected_revision:
        raise _conflict(expected_revision, item.revision)
    try:
        ensure_transition(item.status, TemplateStatus.archived, TEMPLATE_TRANSITIONS)
    except FarmDomainError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    item.status = TemplateStatus.archived
    item.archived_by = actor_id
    item.archived_at = datetime.now(timezone.utc)
    item.revision += 1
    await _audit(session, guild_id=guild_id, actor_id=actor_id, action="farm.template.archived", resource_type="farm_template", resource_id=item.id, correlation_id=correlation_id, after={"version": item.version, "revision": item.revision})
    await session.commit()
    return item


async def activate_template(session: AsyncSession, *, guild_id: str, template_id: int, expected_revision: int, actor_id: str, correlation_id: str) -> FarmTemplate:
    query = select(FarmTemplate).where(FarmTemplate.id == template_id, FarmTemplate.guild_id == guild_id).options(selectinload(FarmTemplate.items)).with_for_update()
    item = (await session.execute(query)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Template nao encontrado.")
    if item.revision != expected_revision:
        raise _conflict(expected_revision, item.revision)
    if not item.items:
        raise HTTPException(status_code=422, detail="Template sem produtos.")
    try:
        ensure_transition(item.status, TemplateStatus.active, TEMPLATE_TRANSITIONS)
    except FarmDomainError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    item.status = TemplateStatus.active
    item.activated_by = actor_id
    item.activated_at = datetime.now(timezone.utc)
    item.revision += 1
    await _audit(session, guild_id=guild_id, actor_id=actor_id, action="farm.template.activated", resource_type="farm_template", resource_id=item.id, correlation_id=correlation_id, after={"version": item.version, "revision": item.revision})
    await session.commit()
    return item


async def list_cycles(session: AsyncSession, guild_id: str) -> list[FarmCycle]:
    query = select(FarmCycle).where(FarmCycle.guild_id == guild_id).options(selectinload(FarmCycle.goals)).order_by(FarmCycle.starts_at.desc())
    return list((await session.execute(query)).scalars().unique())


async def create_cycle(session: AsyncSession, *, guild_id: str, actor_id: str, correlation_id: str, data: CycleCreate) -> FarmCycle:
    instance = (await session.execute(select(ModuleInstance).where(ModuleInstance.guild_id == guild_id, ModuleInstance.module_key == "farm"))).scalar_one_or_none()
    if instance is None or instance.published_config_version_id is None:
        raise HTTPException(status_code=409, detail="Publique a configuracao do Farm antes de criar ciclos.")
    query = select(FarmTemplate).where(FarmTemplate.id == data.template_id, FarmTemplate.guild_id == guild_id, FarmTemplate.status == TemplateStatus.active).options(selectinload(FarmTemplate.items).selectinload(FarmTemplateItem.product))
    template = (await session.execute(query)).scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=422, detail="Template ativo nao encontrado.")
    cycle = FarmCycle(
        guild_id=guild_id,
        template_id=template.id,
        config_version_id=instance.published_config_version_id,
        title=data.title,
        timezone=data.timezone,
        starts_at=data.starts_at,
        ends_at=data.ends_at,
        review_deadline_at=data.review_deadline_at,
        participation_mode=data.participation_mode,
        proof_required=data.proof_required,
        created_by=actor_id,
    )
    session.add(cycle)
    await session.flush()
    for item in sorted(template.items, key=lambda value: value.position):
        cycle.goals.append(FarmCycleGoal(guild_id=guild_id, product_id=item.product_id, product_name=item.product.name, unit=item.product.unit, precision=item.product.precision, quantity_required=item.quantity, position=item.position))
    await _audit(session, guild_id=guild_id, actor_id=actor_id, action="farm.cycle.created", resource_type="farm_cycle", resource_id=cycle.id, correlation_id=correlation_id, after={"title": cycle.title, "goals": len(cycle.goals)})
    await session.commit()
    return cycle


def _task(*, guild_id: str, cycle_id: int, key: str, due_at: datetime, correlation_id: str) -> AutomationTask:
    return AutomationTask(guild_id=guild_id, module_key="farm", job_key=key, resource_type="farm_cycle", resource_id=str(cycle_id), payload={"cycle_id": cycle_id}, due_at=due_at, idempotency_key=f"cycle:{cycle_id}:{key}", correlation_id=correlation_id, max_attempts=10 if key.endswith("finish_closing") else 5)


def _panel_task(*, guild_id: str, panel_key: str, resource_type: str, resource_id: int | str, idempotency_key: str, correlation_id: str) -> AutomationTask:
    return AutomationTask(
        guild_id=guild_id,
        module_key="farm",
        job_key="farm.panel.reconcile",
        resource_type=resource_type,
        resource_id=str(resource_id),
        payload={"panel_key": panel_key, "resource_type": resource_type, "resource_id": str(resource_id)},
        due_at=datetime.now(timezone.utc),
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        max_attempts=5,
    )


async def schedule_cycle(session: AsyncSession, *, guild_id: str, cycle_id: int, expected_revision: int, actor_id: str, correlation_id: str) -> FarmCycle:
    cycle = await _owned(session, FarmCycle, guild_id, cycle_id, lock=True)
    if cycle.revision != expected_revision:
        raise _conflict(expected_revision, cycle.revision)
    try:
        ensure_transition(cycle.status, CycleStatus.scheduled, CYCLE_TRANSITIONS)
    except FarmDomainError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    overlap = int(
        await session.scalar(
            select(func.count(FarmCycle.id)).where(
                FarmCycle.guild_id == guild_id,
                FarmCycle.id != cycle.id,
                FarmCycle.status.in_([CycleStatus.scheduled, CycleStatus.active, CycleStatus.closing]),
                FarmCycle.starts_at < cycle.ends_at,
                FarmCycle.ends_at > cycle.starts_at,
            )
        )
        or 0
    )
    if overlap:
        raise HTTPException(status_code=409, detail="Existe outro ciclo agendado ou ativo no mesmo periodo.")
    cycle.status = CycleStatus.scheduled
    cycle.revision += 1
    session.add_all([
        _task(guild_id=guild_id, cycle_id=cycle.id, key="farm.cycle.start", due_at=cycle.starts_at, correlation_id=correlation_id),
        _task(guild_id=guild_id, cycle_id=cycle.id, key="farm.cycle.begin_closing", due_at=cycle.ends_at, correlation_id=correlation_id),
    ])
    await _audit(session, guild_id=guild_id, actor_id=actor_id, action="farm.cycle.scheduled", resource_type="farm_cycle", resource_id=cycle.id, correlation_id=correlation_id, after={"revision": cycle.revision})
    await session.commit()
    return cycle


async def assign_participant(
    session: AsyncSession,
    *,
    guild_id: str,
    cycle_id: int,
    member_id: str,
    member_display_name: str,
    actor_id: str,
    correlation_id: str,
) -> FarmCycleParticipant:
    cycle = await _owned(session, FarmCycle, guild_id, cycle_id)
    if cycle.participation_mode != ParticipationMode.assigned:
        raise HTTPException(status_code=409, detail="Este ciclo nao usa participacao atribuida.")
    if cycle.status not in {CycleStatus.draft, CycleStatus.scheduled, CycleStatus.active}:
        raise HTTPException(status_code=409, detail="Ciclo nao aceita novas atribuicoes.")
    existing = (
        await session.execute(
            select(FarmCycleParticipant).where(
                FarmCycleParticipant.guild_id == guild_id,
                FarmCycleParticipant.cycle_id == cycle_id,
                FarmCycleParticipant.member_id == member_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    participant = FarmCycleParticipant(
        guild_id=guild_id,
        cycle_id=cycle_id,
        member_id=member_id,
        member_display_name=member_display_name,
        assigned_by=actor_id,
    )
    session.add(participant)
    await session.flush()
    await _audit(
        session,
        guild_id=guild_id,
        actor_id=actor_id,
        action="farm.participant.assigned",
        resource_type="farm_cycle_participant",
        resource_id=participant.id,
        correlation_id=correlation_id,
        after={"cycle_id": cycle_id, "member_id": member_id},
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return (
            await session.execute(
                select(FarmCycleParticipant).where(
                    FarmCycleParticipant.guild_id == guild_id,
                    FarmCycleParticipant.cycle_id == cycle_id,
                    FarmCycleParticipant.member_id == member_id,
                )
            )
        ).scalar_one()
    return participant


async def cancel_cycle(
    session: AsyncSession,
    *,
    guild_id: str,
    cycle_id: int,
    expected_revision: int,
    reason: str,
    actor_id: str,
    correlation_id: str,
) -> FarmCycle:
    cycle = await _owned(session, FarmCycle, guild_id, cycle_id, lock=True)
    if cycle.revision != expected_revision:
        raise _conflict(expected_revision, cycle.revision)
    if not reason.strip():
        raise HTTPException(status_code=422, detail="Motivo obrigatorio para cancelar o ciclo.")
    try:
        ensure_transition(cycle.status, CycleStatus.cancelled, CYCLE_TRANSITIONS)
    except FarmDomainError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    before = {"status": cycle.status, "revision": cycle.revision}
    now = datetime.now(timezone.utc)
    cycle.status = CycleStatus.cancelled
    cycle.cancelled_by = actor_id
    cycle.cancel_reason = reason.strip()
    cycle.cancelled_at = now
    cycle.revision += 1
    await session.execute(
        FarmCycleTicket.__table__.update()
        .where(
            FarmCycleTicket.guild_id == guild_id,
            FarmCycleTicket.cycle_id == cycle.id,
            FarmCycleTicket.status.in_([TicketStatus.open, TicketStatus.completed]),
        )
        .values(status=TicketStatus.cancelled, cancelled_by=actor_id, cancel_reason=reason.strip(), cancelled_at=now)
    )
    await _audit(
        session,
        guild_id=guild_id,
        actor_id=actor_id,
        action="farm.cycle.cancelled",
        resource_type="farm_cycle",
        resource_id=cycle.id,
        correlation_id=correlation_id,
        before=before,
        after={"status": cycle.status, "revision": cycle.revision, "reason": reason.strip()},
    )
    await session.commit()
    return cycle


async def begin_cycle_closing(
    session: AsyncSession,
    *,
    guild_id: str,
    cycle_id: int,
    expected_revision: int,
    actor_id: str,
    correlation_id: str,
) -> FarmCycle:
    cycle = await _owned(session, FarmCycle, guild_id, cycle_id, lock=True)
    if cycle.revision != expected_revision:
        raise _conflict(expected_revision, cycle.revision)
    try:
        ensure_transition(cycle.status, CycleStatus.closing, CYCLE_TRANSITIONS)
    except FarmDomainError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    cycle.status = CycleStatus.closing
    cycle.revision += 1
    pending = int(
        await session.scalar(
            select(func.count(FarmSubmission.id))
            .join(FarmCycleTicket, FarmCycleTicket.id == FarmSubmission.ticket_id)
            .where(
                FarmCycleTicket.cycle_id == cycle.id,
                FarmCycleTicket.guild_id == guild_id,
                FarmSubmission.guild_id == guild_id,
                FarmSubmission.status.in_([SubmissionStatus.submitted, SubmissionStatus.under_review]),
            )
        )
        or 0
    )
    session.add(
        _task(
            guild_id=guild_id,
            cycle_id=cycle.id,
            key="farm.cycle.finish_closing",
            due_at=(cycle.review_deadline_at if pending else None) or datetime.now(timezone.utc),
            correlation_id=correlation_id,
        )
    )
    await _audit(
        session,
        guild_id=guild_id,
        actor_id=actor_id,
        action="farm.cycle.begin_closing",
        resource_type="farm_cycle",
        resource_id=cycle.id,
        correlation_id=correlation_id,
        after={"status": cycle.status, "revision": cycle.revision},
    )
    await session.commit()
    return cycle


async def open_ticket(session: AsyncSession, *, guild_id: str, cycle_id: int, member_id: str, member_display_name: str, actor_id: str, correlation_id: str) -> FarmCycleTicket:
    cycle = await _owned(session, FarmCycle, guild_id, cycle_id)
    if cycle.status != CycleStatus.active:
        raise HTTPException(status_code=409, detail="Ciclo nao esta ativo.")
    if cycle.participation_mode == ParticipationMode.assigned:
        assigned = (await session.execute(select(FarmCycleParticipant.id).where(FarmCycleParticipant.guild_id == guild_id, FarmCycleParticipant.cycle_id == cycle_id, FarmCycleParticipant.member_id == member_id))).scalar_one_or_none()
        if assigned is None:
            raise HTTPException(status_code=403, detail="Membro nao esta atribuido a este ciclo.")
    existing = (await session.execute(select(FarmCycleTicket).where(FarmCycleTicket.guild_id == guild_id, FarmCycleTicket.cycle_id == cycle_id, FarmCycleTicket.member_id == member_id))).scalar_one_or_none()
    if existing is not None:
        return existing
    ticket = FarmCycleTicket(guild_id=guild_id, cycle_id=cycle_id, member_id=member_id, member_display_name=member_display_name, created_by=actor_id)
    session.add(ticket)
    await session.flush()
    await _audit(session, guild_id=guild_id, actor_id=actor_id, action="farm.ticket.opened", resource_type="farm_ticket", resource_id=ticket.id, correlation_id=correlation_id, after={"member_id": member_id, "created_by": actor_id})
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return (
            await session.execute(
                select(FarmCycleTicket).where(
                    FarmCycleTicket.guild_id == guild_id,
                    FarmCycleTicket.cycle_id == cycle_id,
                    FarmCycleTicket.member_id == member_id,
                )
            )
        ).scalar_one()
    return ticket


async def list_tickets(
    session: AsyncSession,
    *,
    guild_id: str,
    cycle_id: int | None = None,
    member_id: str | None = None,
) -> list[FarmCycleTicket]:
    query = select(FarmCycleTicket).where(FarmCycleTicket.guild_id == guild_id)
    if cycle_id is not None:
        query = query.where(FarmCycleTicket.cycle_id == cycle_id)
    if member_id is not None:
        query = query.where(FarmCycleTicket.member_id == member_id)
    query = query.order_by(FarmCycleTicket.created_at.desc()).limit(100)
    return list((await session.execute(query)).scalars())


async def list_review_queue(
    session: AsyncSession,
    *,
    guild_id: str,
    cycle_id: int | None = None,
) -> list[FarmSubmission]:
    query = (
        select(FarmSubmission)
        .join(FarmCycleTicket, FarmCycleTicket.id == FarmSubmission.ticket_id)
        .where(
            FarmSubmission.guild_id == guild_id,
            FarmCycleTicket.guild_id == guild_id,
            FarmSubmission.status.in_([SubmissionStatus.submitted, SubmissionStatus.under_review]),
        )
        .options(
            selectinload(FarmSubmission.items),
            selectinload(FarmSubmission.proofs),
            selectinload(FarmSubmission.ticket),
        )
    )
    if cycle_id is not None:
        query = query.where(FarmCycleTicket.cycle_id == cycle_id)
    query = query.order_by(FarmSubmission.created_at).limit(100)
    return list((await session.execute(query)).scalars().unique())


async def get_ticket(session: AsyncSession, guild_id: str, ticket_id: int) -> FarmCycleTicket:
    query = select(FarmCycleTicket).where(FarmCycleTicket.id == ticket_id, FarmCycleTicket.guild_id == guild_id).options(selectinload(FarmCycleTicket.cycle).selectinload(FarmCycle.goals), selectinload(FarmCycleTicket.submissions).selectinload(FarmSubmission.items), selectinload(FarmCycleTicket.submissions).selectinload(FarmSubmission.proofs))
    item = (await session.execute(query)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Ticket nao encontrado.")
    return item


async def get_submission(session: AsyncSession, guild_id: str, submission_id: int) -> FarmSubmission:
    query = select(FarmSubmission).where(FarmSubmission.id == submission_id, FarmSubmission.guild_id == guild_id).options(selectinload(FarmSubmission.items), selectinload(FarmSubmission.proofs))
    item = (await session.execute(query)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Entrega nao encontrada.")
    return item


async def create_submission(session: AsyncSession, *, guild_id: str, ticket_id: int, actor_id: str, correlation_id: str, data: SubmissionCreate) -> FarmSubmission:
    existing = (await session.execute(select(FarmSubmission).where(FarmSubmission.guild_id == guild_id, FarmSubmission.idempotency_key == data.idempotency_key))).scalar_one_or_none()
    if existing is not None:
        return await get_submission(session, guild_id, existing.id)
    ticket = await get_ticket(session, guild_id, ticket_id)
    if ticket.status != TicketStatus.open or ticket.cycle.status != CycleStatus.active:
        raise HTTPException(status_code=409, detail="Ticket nao aceita novas entregas.")
    if data.submitted_by != actor_id:
        raise HTTPException(status_code=403, detail="Executor divergente.")
    if ticket.cycle.proof_required and not data.proofs:
        raise HTTPException(status_code=422, detail="Comprovante obrigatorio.")
    goals = {goal.id: goal for goal in ticket.cycle.goals}
    if not {item.goal_id for item in data.items}.issubset(goals):
        raise HTTPException(status_code=422, detail="Entrega referencia meta de outro ciclo.")
    if data.correction_of_submission_id is not None:
        corrected = next((item for item in ticket.submissions if item.id == data.correction_of_submission_id), None)
        if corrected is None or corrected.status != SubmissionStatus.correction_requested:
            raise HTTPException(status_code=422, detail="Submissao original nao aceita correcao.")
    submission = FarmSubmission(guild_id=guild_id, ticket_id=ticket.id, correction_of_submission_id=data.correction_of_submission_id, submitted_by=actor_id, note=data.note, idempotency_key=data.idempotency_key)
    session.add(submission)
    await session.flush()
    for requested in data.items:
        try:
            quantity = normalize_quantity(requested.quantity, goals[requested.goal_id].precision)
        except FarmDomainError as exc:
            raise HTTPException(status_code=422, detail=f"{goals[requested.goal_id].product_name}: {exc}") from exc
        submission.items.append(FarmSubmissionItem(guild_id=guild_id, goal_id=requested.goal_id, quantity=quantity))
    for proof in data.proofs:
        submission.proofs.append(FarmProof(guild_id=guild_id, channel_id=proof.channel_id, message_id=proof.message_id, attachment_id=proof.attachment_id, url=proof.url, content_type=proof.content_type, submitted_by=actor_id))
    await _audit(session, guild_id=guild_id, actor_id=actor_id, action="farm.submission.created", resource_type="farm_submission", resource_id=submission.id, correlation_id=correlation_id, after={"ticket_id": ticket.id, "items": len(submission.items), "proofs": len(submission.proofs)})
    config = await _published_config(session, guild_id)
    await _enqueue(
        session,
        guild_id=guild_id,
        renderer_key="farm.review_pending",
        destination_id=config.get("review_panel_channel_id"),
        resource_type="farm_submission",
        resource_id=submission.id,
        payload={
            "submission_id": submission.id,
            "ticket_id": ticket.id,
            "member_id": ticket.member_id,
            "member_display_name": ticket.member_display_name,
        },
        idempotency_key=f"submission:{submission.id}:review_pending",
        correlation_id=correlation_id,
    )
    session.add(
        _panel_task(
            guild_id=guild_id,
            panel_key="review",
            resource_type="",
            resource_id="",
            idempotency_key=f"submission:{submission.id}:panel:review:created",
            correlation_id=correlation_id,
        )
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        duplicate = (
            await session.execute(
                select(FarmSubmission.id).where(
                    FarmSubmission.guild_id == guild_id,
                    FarmSubmission.idempotency_key == data.idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if duplicate is None:
            raise HTTPException(status_code=409, detail="Entrega concorrente em conflito.") from exc
        return await get_submission(session, guild_id, duplicate)
    return submission


async def ticket_progress(session: AsyncSession, *, guild_id: str, ticket_id: int):
    ticket = await get_ticket(session, guild_id, ticket_id)
    approved = [(item.goal_id, item.quantity) for submission in ticket.submissions if submission.status == SubmissionStatus.approved for item in submission.items]
    return calculate_progress({goal.id: goal.quantity_required for goal in ticket.cycle.goals}, approved)


async def review_submission(session: AsyncSession, *, guild_id: str, submission_id: int, actor_id: str, correlation_id: str, data: ReviewCreate) -> FarmSubmission:
    existing = (await session.execute(select(FarmReview).where(FarmReview.guild_id == guild_id, FarmReview.idempotency_key == data.idempotency_key))).scalar_one_or_none()
    if existing is not None:
        return await get_submission(session, guild_id, existing.submission_id)
    query = select(FarmSubmission).where(FarmSubmission.id == submission_id, FarmSubmission.guild_id == guild_id).options(selectinload(FarmSubmission.items), selectinload(FarmSubmission.proofs), selectinload(FarmSubmission.ticket).selectinload(FarmCycleTicket.cycle).selectinload(FarmCycle.goals), selectinload(FarmSubmission.ticket).selectinload(FarmCycleTicket.submissions).selectinload(FarmSubmission.items)).with_for_update()
    submission = (await session.execute(query)).scalar_one_or_none()
    if submission is None:
        raise HTTPException(status_code=404, detail="Entrega nao encontrada.")
    target = SubmissionStatus(data.decision.value)
    try:
        ensure_transition(submission.status, target, SUBMISSION_TRANSITIONS)
    except FarmDomainError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    submission.status = target
    submission.decided_at = datetime.now(timezone.utc)
    submission.revision += 1
    submission.claimed_by = None
    submission.claim_expires_at = None
    review = FarmReview(guild_id=guild_id, submission_id=submission.id, decision=data.decision, reviewer_id=actor_id, reason=data.reason, idempotency_key=data.idempotency_key)
    session.add(review)
    await session.flush()
    ticket = submission.ticket
    approved = [(item.goal_id, item.quantity) for candidate in ticket.submissions if candidate.status == SubmissionStatus.approved for item in candidate.items]
    progress = calculate_progress({goal.id: goal.quantity_required for goal in ticket.cycle.goals}, approved)
    if progress.completed and ticket.status == TicketStatus.open:
        ticket.status = TicketStatus.completed
        ticket.completed_at = datetime.now(timezone.utc)
        ticket.revision += 1
    elif not progress.completed and ticket.status == TicketStatus.completed:
        ticket.status = TicketStatus.open
        ticket.completed_at = None
        ticket.revision += 1
    await _audit(session, guild_id=guild_id, actor_id=actor_id, action="farm.submission.reviewed", resource_type="farm_submission", resource_id=submission.id, correlation_id=correlation_id, after={"decision": target, "ticket_percent": str(progress.percent)})
    config = await _published_config(session, guild_id)
    await _enqueue(
        session,
        guild_id=guild_id,
        renderer_key="farm.audit",
        destination_id=config.get("log_channel_id"),
        resource_type="farm_submission",
        resource_id=submission.id,
        payload={
            "event": "submission_reviewed",
            "submission_id": submission.id,
            "ticket_id": ticket.id,
            "member_id": ticket.member_id,
            "decision": target.value,
            "reviewer_id": actor_id,
            "reason": data.reason,
            "progress_percent": str(progress.percent),
        },
        idempotency_key=f"submission:{submission.id}:review:{review.id}",
        correlation_id=correlation_id,
    )
    session.add_all(
        [
            _panel_task(
                guild_id=guild_id,
                panel_key="ticket",
                resource_type="farm_ticket",
                resource_id=ticket.id,
                idempotency_key=f"submission:{submission.id}:panel:ticket:reviewed",
                correlation_id=correlation_id,
            ),
            _panel_task(
                guild_id=guild_id,
                panel_key="review",
                resource_type="",
                resource_id="",
                idempotency_key=f"submission:{submission.id}:panel:review:reviewed",
                correlation_id=correlation_id,
            ),
        ]
    )
    if ticket.cycle.status == CycleStatus.closing:
        remaining = int(
            await session.scalar(
                select(func.count(FarmSubmission.id))
                .join(FarmCycleTicket, FarmCycleTicket.id == FarmSubmission.ticket_id)
                .where(
                    FarmCycleTicket.cycle_id == ticket.cycle_id,
                    FarmCycleTicket.guild_id == guild_id,
                    FarmSubmission.guild_id == guild_id,
                    FarmSubmission.status.in_([SubmissionStatus.submitted, SubmissionStatus.under_review]),
                )
            )
            or 0
        )
        if remaining == 0:
            task = (
                await session.execute(
                    select(AutomationTask).where(
                        AutomationTask.guild_id == guild_id,
                        AutomationTask.module_key == "farm",
                        AutomationTask.idempotency_key == f"cycle:{ticket.cycle_id}:farm.cycle.finish_closing",
                    )
                )
            ).scalar_one_or_none()
            if task is not None and task.state in {WorkState.pending, WorkState.retry}:
                task.due_at = datetime.now(timezone.utc)
            else:
                session.add(
                    AutomationTask(
                        guild_id=guild_id,
                        module_key="farm",
                        job_key="farm.cycle.finish_closing",
                        resource_type="farm_cycle",
                        resource_id=str(ticket.cycle_id),
                        payload={"cycle_id": ticket.cycle_id},
                        due_at=datetime.now(timezone.utc),
                        idempotency_key=f"cycle:{ticket.cycle_id}:finish-after-review:{submission.id}",
                        correlation_id=correlation_id,
                        max_attempts=10,
                    )
                )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        duplicate = (
            await session.execute(
                select(FarmReview.submission_id).where(
                    FarmReview.guild_id == guild_id,
                    FarmReview.idempotency_key == data.idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if duplicate is None:
            raise HTTPException(status_code=409, detail="Revisao concorrente em conflito.") from exc
        return await get_submission(session, guild_id, duplicate)
    return submission


async def process_cycle_job(session: AsyncSession, *, guild_id: str, cycle_id: int, job_key: str, correlation_id: str) -> dict[str, Any]:
    cycle = await _owned(session, FarmCycle, guild_id, cycle_id, lock=True)
    now = datetime.now(timezone.utc)
    changed = False
    if job_key == "farm.cycle.start" and cycle.status == CycleStatus.scheduled:
        cycle.status = CycleStatus.active
        cycle.activated_at = now
        changed = True
    elif job_key == "farm.cycle.begin_closing" and cycle.status == CycleStatus.active:
        cycle.status = CycleStatus.closing
        changed = True
    elif job_key == "farm.cycle.finish_closing" and cycle.status == CycleStatus.closing:
        pending = (await session.execute(select(func.count(FarmSubmission.id)).join(FarmCycleTicket, FarmCycleTicket.id == FarmSubmission.ticket_id).where(FarmCycleTicket.guild_id == guild_id, FarmSubmission.guild_id == guild_id, FarmCycleTicket.cycle_id == cycle.id, FarmSubmission.status.in_([SubmissionStatus.submitted, SubmissionStatus.under_review])))).scalar_one()
        if pending:
            raise HTTPException(status_code=409, detail={"detail": "Ciclo ainda possui revisoes pendentes.", "pending_reviews": pending})
        cycle.status = CycleStatus.closed
        cycle.closed_at = now
        await session.execute(FarmCycleTicket.__table__.update().where(FarmCycleTicket.guild_id == guild_id, FarmCycleTicket.cycle_id == cycle.id, FarmCycleTicket.status.in_([TicketStatus.open, TicketStatus.completed])).values(status=TicketStatus.closed, closed_at=now))
        changed = True
    if changed:
        cycle.revision += 1
        await _audit(session, guild_id=guild_id, actor_id=None, action=job_key, resource_type="farm_cycle", resource_id=cycle.id, correlation_id=correlation_id, after={"status": cycle.status})
        session.add_all(
            [
                _panel_task(
                    guild_id=guild_id,
                    panel_key="public",
                    resource_type="farm_cycle",
                    resource_id=cycle.id,
                    idempotency_key=f"cycle:{cycle.id}:panel:public:{cycle.status.value}",
                    correlation_id=correlation_id,
                ),
                _panel_task(
                    guild_id=guild_id,
                    panel_key="review",
                    resource_type="",
                    resource_id="",
                    idempotency_key=f"cycle:{cycle.id}:panel:review:{cycle.status.value}",
                    correlation_id=correlation_id,
                ),
            ]
        )
        if cycle.status == CycleStatus.closing:
            pending = int(
                await session.scalar(
                    select(func.count(FarmSubmission.id))
                    .join(FarmCycleTicket, FarmCycleTicket.id == FarmSubmission.ticket_id)
                    .where(
                        FarmCycleTicket.cycle_id == cycle.id,
                        FarmCycleTicket.guild_id == guild_id,
                        FarmSubmission.guild_id == guild_id,
                        FarmSubmission.status.in_([SubmissionStatus.submitted, SubmissionStatus.under_review]),
                    )
                )
                or 0
            )
            session.add(_task(guild_id=guild_id, cycle_id=cycle.id, key="farm.cycle.finish_closing", due_at=(cycle.review_deadline_at if pending else None) or now, correlation_id=correlation_id))
        await session.commit()
    return {"changed": changed, "status": cycle.status}


async def legacy_inventory(session: AsyncSession, *, guild_id: str) -> dict[str, Any]:
    """Inventario somente leitura; nunca transforma nem importa dados antigos."""

    tables = (
        "farm_ticket_configs",
        "farm_weekly_goals",
        "farm_tickets",
        "farm_ticket_entries",
        "farm_ticket_actions",
    )
    counts: dict[str, int] = {}
    for table_name in tables:
        counts[table_name] = int(
            await session.scalar(
                text(f"SELECT count(*) FROM {table_name} WHERE guild_id = :guild_id"),
                {"guild_id": guild_id},
            )
            or 0
        )
    active_legacy_tickets = int(
        await session.scalar(
            text(
                "SELECT count(*) FROM farm_tickets "
                "WHERE guild_id = :guild_id AND deleted_at IS NULL "
                "AND status NOT IN ('finalizado', 'excluido', 'cancelado')"
            ),
            {"guild_id": guild_id},
        )
        or 0
    )
    domain_counts = {
        "products": int(await session.scalar(select(func.count(FarmProduct.id)).where(FarmProduct.guild_id == guild_id)) or 0),
        "templates": int(await session.scalar(select(func.count(FarmTemplate.id)).where(FarmTemplate.guild_id == guild_id)) or 0),
        "cycles": int(await session.scalar(select(func.count(FarmCycle.id)).where(FarmCycle.guild_id == guild_id)) or 0),
        "tickets": int(await session.scalar(select(func.count(FarmCycleTicket.id)).where(FarmCycleTicket.guild_id == guild_id)) or 0),
        "submissions": int(await session.scalar(select(func.count(FarmSubmission.id)).where(FarmSubmission.guild_id == guild_id)) or 0),
    }
    return {
        "migration_key": "farm-v2",
        "automatic_import": False,
        "legacy_counts": counts,
        "active_legacy_tickets": active_legacy_tickets,
        "domain_counts": domain_counts,
        "cutover_ready": active_legacy_tickets == 0,
        "warnings": (
            ["Existem tickets legados ativos; encerre-os antes do cutover."]
            if active_legacy_tickets
            else []
        ),
    }
