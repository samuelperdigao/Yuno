from __future__ import annotations

from typing import Any, Awaitable

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.platform.dependencies import (
    ActorHeader,
    CorrelationHeader,
    require_active_license,
)
from app.core.security import require_bot_token
from app.db import get_session
from app.domain_modules.farm_tickets import proof_processing, services
from app.domain_modules.farm_tickets.domain import (
    FarmTicketConflict,
    FarmTicketError,
    FarmTicketNotFound,
)
from app.domain_modules.farm_tickets.schemas import (
    AssignTicketIn,
    AutomationIn,
    BeginOperationIn,
    CloseTicketIn,
    DiscordBindingIn,
    MetaConsumeIn,
    OpenFormIn,
    OpenTicketIn,
    ProofClaimIn,
    ProofDeliveredIn,
    ProofProcessIn,
    ProvisioningErrorIn,
    ReconcileIn,
    ResourceDeletedIn,
    SaveFormStepIn,
    WithdrawalIn,
)
from app.object_storage import ObjectStorageError, get_object_storage
from app.platform.permissions import authorize
from app.platform.schemas import ActorContextIn

router = APIRouter(dependencies=[Depends(require_bot_token)])


async def _permit(
    session: AsyncSession,
    *,
    guild_id: str,
    capability: str,
    actor: ActorContextIn,
    actor_header: str,
    correlation_header: str | None,
    resource_id: str = "",
    resource_owner_id: str | None = None,
) -> None:
    if actor.guild_id != guild_id:
        raise HTTPException(
            status_code=403, detail="ActorContext pertence a outra guild."
        )
    if actor.actor_type == "user" and actor.user_id != actor_header:
        raise HTTPException(status_code=403, detail="Ator autenticado divergente.")
    if correlation_header and correlation_header != actor.correlation_id:
        raise HTTPException(status_code=400, detail="Correlation ID divergente.")
    trusted_actor = actor.model_copy(update={"resource_owner_id": resource_owner_id})
    decision = await authorize(
        session,
        guild_id=guild_id,
        module_key="farm_tickets",
        capability_key=capability,
        actor=trusted_actor,
        resource_id=resource_id,
    )
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)


async def _domain(call: Awaitable[Any]) -> Any:
    try:
        return await call
    except FarmTicketNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FarmTicketConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FarmTicketError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _authorize_ticket(
    session: AsyncSession,
    *,
    guild_id: str,
    ticket_id: str,
    capability: str,
    actor: ActorContextIn,
    actor_header: str,
    correlation_header: str | None,
) -> dict[str, Any]:
    ticket = await _domain(
        services.get_ticket(session, guild_id=guild_id, ticket_id=ticket_id)
    )
    await _permit(
        session,
        guild_id=guild_id,
        capability=capability,
        actor=actor,
        actor_header=actor_header,
        correlation_header=correlation_header,
        resource_id=ticket_id,
        resource_owner_id=ticket["member_id"],
    )
    return ticket


@router.post("/guilds/{guild_id}/modules/farm_tickets/tickets/open")
async def open_ticket(
    guild_id: str,
    data: OpenTicketIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    own = data.actor.user_id == data.member_id
    await _permit(
        session,
        guild_id=guild_id,
        capability="farm_tickets.open_own" if own else "farm_tickets.open_for_member",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
        resource_id=data.member_id,
        resource_owner_id=data.member_id,
    )
    return await _domain(
        services.open_ticket(
            session,
            guild_id=guild_id,
            member_id=data.member_id,
            actor=data.actor,
            idempotency_key=data.idempotency_key,
        )
    )


@router.get("/guilds/{guild_id}/modules/farm_tickets/tickets/{ticket_id}")
async def get_ticket(
    guild_id: str,
    ticket_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    return await _domain(
        services.get_ticket(session, guild_id=guild_id, ticket_id=ticket_id)
    )


@router.get("/guilds/{guild_id}/modules/farm_tickets/members/{member_id}/active-ticket")
async def active_ticket(
    guild_id: str,
    member_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict | None:
    await require_active_license(session, guild_id)
    return await services.get_active_ticket_for_member(
        session, guild_id=guild_id, member_id=member_id
    )


@router.get("/guilds/{guild_id}/modules/farm_tickets/tickets")
async def tickets(
    guild_id: str,
    active_only: bool = Query(default=True),
    reconcile_only: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    await require_active_license(session, guild_id)
    return await services.list_tickets(
        session,
        guild_id=guild_id,
        active_only=active_only,
        reconcile_only=reconcile_only,
    )


@router.get(
    "/guilds/{guild_id}/modules/farm_tickets/channels/{channel_id}/active-operation"
)
async def channel_active_operation(
    guild_id: str,
    channel_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict | None:
    await require_active_license(session, guild_id)
    return await services.get_active_operation_for_channel(
        session, guild_id=guild_id, channel_id=channel_id
    )


@router.post("/guilds/{guild_id}/modules/farm_tickets/tickets/{ticket_id}/operations")
async def begin_operation(
    guild_id: str,
    ticket_id: str,
    data: BeginOperationIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    capability = (
        "farm_tickets.edit"
        if data.kind.value == "EDIT_ENTRY"
        else "farm_tickets.submit"
    )
    await _authorize_ticket(
        session,
        guild_id=guild_id,
        ticket_id=ticket_id,
        capability=capability,
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    return await _domain(
        services.begin_operation(
            session,
            guild_id=guild_id,
            ticket_id=ticket_id,
            actor=data.actor,
            expected_version=data.expected_version,
            idempotency_key=data.idempotency_key,
            kind=data.kind,
            values=[(item.objective_id, item.amount) for item in data.values],
            target_entry_id=data.target_entry_id,
            interaction_id=data.interaction_id,
        )
    )


@router.post("/guilds/{guild_id}/modules/farm_tickets/tickets/{ticket_id}/form-drafts")
async def open_form_draft(
    guild_id: str,
    ticket_id: str,
    data: OpenFormIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    capability = {
        "EDIT_ENTRY": "farm_tickets.edit",
        "WITHDRAWAL": "farm_tickets.withdraw",
    }.get(data.kind.value, "farm_tickets.submit")
    await _authorize_ticket(
        session,
        guild_id=guild_id,
        ticket_id=ticket_id,
        capability=capability,
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    return await _domain(
        services.open_form_draft(
            session,
            guild_id=guild_id,
            ticket_id=ticket_id,
            actor=data.actor,
            expected_version=data.expected_version,
            kind=data.kind,
            target_entry_id=data.target_entry_id,
        )
    )


@router.post(
    "/guilds/{guild_id}/modules/farm_tickets/tickets/{ticket_id}/form-drafts/{draft_id}/steps"
)
async def save_form_step(
    guild_id: str,
    ticket_id: str,
    draft_id: str,
    data: SaveFormStepIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    await _authorize_ticket(
        session,
        guild_id=guild_id,
        ticket_id=ticket_id,
        capability="farm_tickets.submit",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    return await _domain(
        services.save_form_step(
            session,
            guild_id=guild_id,
            ticket_id=ticket_id,
            draft_id=draft_id,
            actor=data.actor,
            expected_version=data.expected_version,
            draft_revision=data.draft_revision,
            step=data.step,
            values=[(item.objective_id, item.amount) for item in data.values],
            idempotency_key=data.idempotency_key,
            interaction_id=data.interaction_id,
        )
    )


@router.post(
    "/guilds/{guild_id}/modules/farm_tickets/tickets/{ticket_id}/operations/{operation_id}/proof/claim"
)
async def claim_proof(
    guild_id: str,
    ticket_id: str,
    operation_id: str,
    data: ProofClaimIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    await _authorize_ticket(
        session,
        guild_id=guild_id,
        ticket_id=ticket_id,
        capability="farm_tickets.submit",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    return await _domain(
        services.claim_proof(
            session,
            guild_id=guild_id,
            ticket_id=ticket_id,
            operation_id=operation_id,
            actor=data.actor,
            expected_version=data.expected_version,
            message_id=data.message_id,
            attachment_id=data.attachment_id,
            author_id=data.author_id,
            channel_id=data.channel_id,
            received_at=data.received_at,
            filename=data.filename,
            content_type=data.content_type,
            size_bytes=data.size_bytes,
            source_url=data.source_url,
        )
    )


@router.post(
    "/guilds/{guild_id}/modules/farm_tickets/tickets/{ticket_id}/operations/{operation_id}/proof/process"
)
async def process_proof(
    guild_id: str,
    ticket_id: str,
    operation_id: str,
    data: ProofProcessIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    await _permit(
        session,
        guild_id=guild_id,
        capability="farm_tickets.automation",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
        resource_id=ticket_id,
    )
    try:
        storage = get_object_storage()
    except ObjectStorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return await _domain(
        proof_processing.process_claimed_proof(
            session,
            storage=storage,
            guild_id=guild_id,
            ticket_id=ticket_id,
            operation_id=operation_id,
            claim_token=data.claim_token,
        )
    )


@router.post("/guilds/{guild_id}/modules/farm_tickets/operations/{operation_id}/expire")
async def expire_operation(
    guild_id: str,
    operation_id: str,
    data: AutomationIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    await _permit(
        session,
        guild_id=guild_id,
        capability="farm_tickets.automation",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
        resource_id=operation_id,
    )
    return {
        "expired": await _domain(
            services.expire_operation(
                session, guild_id=guild_id, operation_id=operation_id
            )
        )
    }


@router.get("/guilds/{guild_id}/modules/farm_tickets/tickets/{ticket_id}/proofs")
async def proofs(
    guild_id: str,
    ticket_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    await require_active_license(session, guild_id)
    rows = await _domain(
        services.list_proofs(session, guild_id=guild_id, ticket_id=ticket_id)
    )
    try:
        storage = get_object_storage()
    except ObjectStorageError:
        return rows
    for item in rows:
        if item["storage_state"] != "DELETED":
            item["url"] = await storage.presign_get(key=item["object_key"])
    return rows


@router.get("/guilds/{guild_id}/modules/farm_tickets/tickets/{ticket_id}/entries")
async def entries(
    guild_id: str,
    ticket_id: str,
    editable_only: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    await require_active_license(session, guild_id)
    return await _domain(
        services.list_entries(
            session,
            guild_id=guild_id,
            ticket_id=ticket_id,
            editable_only=editable_only,
        )
    )


@router.post("/guilds/{guild_id}/modules/farm_tickets/tickets/{ticket_id}/withdrawals")
async def withdraw(
    guild_id: str,
    ticket_id: str,
    data: WithdrawalIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    await _authorize_ticket(
        session,
        guild_id=guild_id,
        ticket_id=ticket_id,
        capability="farm_tickets.withdraw",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    return await _domain(
        services.withdraw(
            session,
            guild_id=guild_id,
            ticket_id=ticket_id,
            actor=data.actor,
            expected_version=data.expected_version,
            idempotency_key=data.idempotency_key,
            values=[(item.objective_id, item.amount) for item in data.values],
        )
    )


@router.post("/guilds/{guild_id}/modules/farm_tickets/tickets/{ticket_id}/assign")
async def assign(
    guild_id: str,
    ticket_id: str,
    data: AssignTicketIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    await _authorize_ticket(
        session,
        guild_id=guild_id,
        ticket_id=ticket_id,
        capability="farm_tickets.assign",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    return await _domain(
        services.assign_ticket(
            session,
            guild_id=guild_id,
            ticket_id=ticket_id,
            actor=data.actor,
            expected_version=data.expected_version,
            idempotency_key=data.idempotency_key,
            administrator_id=data.administrator_id,
        )
    )


async def _close(
    *,
    capability: str,
    action,
    guild_id: str,
    ticket_id: str,
    data: CloseTicketIn,
    actor_header: str,
    correlation_header: str | None,
    session: AsyncSession,
) -> dict:
    await require_active_license(session, guild_id)
    await _authorize_ticket(
        session,
        guild_id=guild_id,
        ticket_id=ticket_id,
        capability=capability,
        actor=data.actor,
        actor_header=actor_header,
        correlation_header=correlation_header,
    )
    return await _domain(
        action(
            session=session,
            guild_id=guild_id,
            ticket_id=ticket_id,
            actor=data.actor,
            expected_version=data.expected_version,
            idempotency_key=data.idempotency_key,
        )
    )


@router.post("/guilds/{guild_id}/modules/farm_tickets/tickets/{ticket_id}/approve")
async def approve(
    guild_id: str,
    ticket_id: str,
    data: CloseTicketIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await _close(
        capability="farm_tickets.approve",
        action=services.approve_ticket,
        guild_id=guild_id,
        ticket_id=ticket_id,
        data=data,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
        session=session,
    )


@router.post("/guilds/{guild_id}/modules/farm_tickets/tickets/{ticket_id}/finalize")
async def finalize(
    guild_id: str,
    ticket_id: str,
    data: CloseTicketIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await _close(
        capability="farm_tickets.finalize",
        action=services.finalize_ticket,
        guild_id=guild_id,
        ticket_id=ticket_id,
        data=data,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
        session=session,
    )


@router.post("/guilds/{guild_id}/modules/farm_tickets/tickets/{ticket_id}/delete")
async def delete(
    guild_id: str,
    ticket_id: str,
    data: CloseTicketIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await _close(
        capability="farm_tickets.delete",
        action=services.delete_ticket,
        guild_id=guild_id,
        ticket_id=ticket_id,
        data=data,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
        session=session,
    )


@router.post("/guilds/{guild_id}/modules/farm_tickets/meta-events/consume")
async def consume_meta_events(
    guild_id: str,
    data: MetaConsumeIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    await _permit(
        session,
        guild_id=guild_id,
        capability="farm_tickets.automation",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    return await _domain(
        services.consume_meta_events(session, guild_id=guild_id, limit=data.limit)
    )


@router.post("/guilds/{guild_id}/modules/farm_tickets/resources/deleted")
async def resource_deleted(
    guild_id: str,
    data: ResourceDeletedIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    await _permit(
        session,
        guild_id=guild_id,
        capability="farm_tickets.automation",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    return await _domain(
        services.record_external_resource_deletion(
            session,
            guild_id=guild_id,
            resource_id=data.resource_id,
            observed_at=data.observed_at,
        )
    )


@router.get("/guilds/{guild_id}/modules/farm_tickets/diagnostics")
async def diagnostics(
    guild_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    return await services.diagnose(session, guild_id=guild_id)


@router.get("/guilds/{guild_id}/modules/farm_tickets/bindings")
async def bindings(
    guild_id: str,
    ticket_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    await require_active_license(session, guild_id)
    return await services.list_discord_bindings(
        session, guild_id=guild_id, ticket_id=ticket_id
    )


@router.post("/guilds/{guild_id}/modules/farm_tickets/bindings")
async def upsert_binding(
    guild_id: str,
    data: DiscordBindingIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    await _permit(
        session,
        guild_id=guild_id,
        capability="farm_tickets.automation",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
        resource_id=data.ticket_id or guild_id,
    )
    return await _domain(
        services.upsert_discord_binding(
            session,
            guild_id=guild_id,
            ticket_id=data.ticket_id,
            kind=data.kind,
            resource_id=data.resource_id,
            parent_resource_id=data.parent_resource_id,
            ownership=data.ownership,
            idempotency_key=data.idempotency_key,
        )
    )


@router.post("/guilds/{guild_id}/modules/farm_tickets/bindings/{binding_id}/deleted")
async def binding_deleted(
    guild_id: str,
    binding_id: str,
    data: AutomationIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    await _permit(
        session,
        guild_id=guild_id,
        capability="farm_tickets.automation",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
        resource_id=binding_id,
    )
    return await _domain(
        services.mark_discord_binding_deleted(
            session, guild_id=guild_id, binding_id=binding_id
        )
    )


@router.post(
    "/guilds/{guild_id}/modules/farm_tickets/tickets/{ticket_id}/provisioning-error"
)
async def provisioning_error(
    guild_id: str,
    ticket_id: str,
    data: ProvisioningErrorIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    await _permit(
        session,
        guild_id=guild_id,
        capability="farm_tickets.automation",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
        resource_id=ticket_id,
    )
    return await _domain(
        services.set_provisioning_error(
            session, guild_id=guild_id, ticket_id=ticket_id, error=data.error
        )
    )


@router.get("/guilds/{guild_id}/modules/farm_tickets/tickets/{ticket_id}/cleanup-state")
async def cleanup_state(
    guild_id: str,
    ticket_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    return await _domain(
        services.ticket_cleanup_state(session, guild_id=guild_id, ticket_id=ticket_id)
    )


@router.post(
    "/guilds/{guild_id}/modules/farm_tickets/tickets/{ticket_id}/cleanup-storage"
)
async def cleanup_storage(
    guild_id: str,
    ticket_id: str,
    data: AutomationIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    await _permit(
        session,
        guild_id=guild_id,
        capability="farm_tickets.automation",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
        resource_id=ticket_id,
    )
    try:
        storage = get_object_storage()
    except ObjectStorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return await _domain(
        proof_processing.cleanup_released_ticket_proofs(
            session, storage=storage, guild_id=guild_id, ticket_id=ticket_id
        )
    )


@router.post(
    "/guilds/{guild_id}/modules/farm_tickets/tickets/{ticket_id}/proofs/{proof_id}/thread-delivered"
)
async def proof_thread_delivered(
    guild_id: str,
    ticket_id: str,
    proof_id: str,
    data: ProofDeliveredIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    await _permit(
        session,
        guild_id=guild_id,
        capability="farm_tickets.automation",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
        resource_id=ticket_id,
    )
    return await _domain(
        services.mark_proof_thread_delivered(
            session,
            guild_id=guild_id,
            ticket_id=ticket_id,
            proof_id=proof_id,
            external_message_id=data.external_message_id,
        )
    )


@router.post("/guilds/{guild_id}/modules/farm_tickets/reconcile")
async def reconcile(
    guild_id: str,
    data: ReconcileIn,
    x_yuno_actor_id: ActorHeader,
    x_yuno_correlation_id: CorrelationHeader = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_active_license(session, guild_id)
    await _permit(
        session,
        guild_id=guild_id,
        capability="farm_tickets.diagnose",
        actor=data.actor,
        actor_header=x_yuno_actor_id,
        correlation_header=x_yuno_correlation_id,
    )
    return await services.request_reconciliation(
        session,
        guild_id=guild_id,
        actor_id=data.actor.user_id or "Yuno",
        idempotency_key=data.idempotency_key,
        correlation_id=data.actor.correlation_id,
    )
