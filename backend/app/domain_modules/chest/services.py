from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, func, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain_modules.chest.domain import (
    MovementType,
    apply_movement,
    compact_text,
    normalize_name,
    quantity,
)
from app.domain_modules.chest.models import (
    Chest,
    ChestBalance,
    ChestCommandReceipt,
    ChestDraftChest,
    ChestDraftItem,
    ChestDraftLink,
    ChestItem,
    ChestMovement,
    ChestVersionChest,
    ChestVersionItem,
    ChestVersionLink,
)
from app.platform.audit import write_audit
from app.platform.configuration import (
    get_or_create_draft,
)
from app.platform.configuration import (
    publish as publish_configuration,
)
from app.platform.configuration import (
    save_draft as save_platform_draft,
)
from app.platform.lifecycle import ensure_module_instance
from app.platform.models import (
    ModuleConfigDraft,
    ModuleConfigVersion,
    PanelInstance,
    PanelState,
)
from app.platform.outbox import enqueue_delivery
from app.platform.permissions import authorize
from app.platform.schemas import ActorContextIn, PermissionGrantIn

MODULE_KEY = "chest"


def _http(status: int, detail: str, **extra: Any) -> HTTPException:
    return HTTPException(
        status_code=status, detail={"detail": detail, **extra} if extra else detail
    )


def _actor_id(actor: ActorContextIn) -> str:
    return actor.user_id or "system"


def _grants_from_chests(rows: list[ChestDraftChest]) -> list[PermissionGrantIn]:
    mapping = {
        "view_role_ids": ("chest.view",),
        "deposit_role_ids": ("chest.deposit",),
        "withdraw_role_ids": ("chest.withdraw",),
        "admin_role_ids": ("chest.view", "chest.deposit", "chest.withdraw", "chest.history"),
    }
    result: list[PermissionGrantIn] = []
    for row in rows:
        if not row.active:
            continue
        for field, capabilities in mapping.items():
            for role_id in list(getattr(row, field, None) or []):
                for capability in capabilities:
                    result.append(
                        PermissionGrantIn(
                            capability=capability,
                            subject_type="everyone" if role_id == "everyone" else "role",
                            subject_id="" if role_id == "everyone" else str(role_id),
                            scope_type="resource",
                            scope_id=row.chest_id,
                        )
                    )
    return result


async def _require(
    session: AsyncSession,
    *,
    guild_id: str,
    capability: str,
    actor: ActorContextIn,
    resource_id: str = "",
) -> None:
    result = await authorize(
        session,
        guild_id=guild_id,
        module_key=MODULE_KEY,
        capability_key=capability,
        actor=actor,
        resource_id=resource_id,
    )
    if not result.allowed:
        raise _http(403, result.reason)


async def _receipt(
    session: AsyncSession, *, guild_id: str, idempotency_key: str, action: str
) -> ChestCommandReceipt | None:
    # Serializa comandos administrativos da guild antes de consultar a chave.
    # Assim uma repeticao concorrente observa o receipt gravado pela primeira.
    await ensure_module_instance(
        session, guild_id=guild_id, module_key=MODULE_KEY, for_update=True
    )
    item = (
        await session.execute(
            select(ChestCommandReceipt).where(
                ChestCommandReceipt.guild_id == guild_id,
                ChestCommandReceipt.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if item is not None and item.action != action:
        raise _http(409, "A chave de idempotencia ja foi usada por outra acao.")
    return item


async def publish_catalog(
    session: AsyncSession,
    *,
    guild_id: str,
    expected_revision: int,
    expected_published_version: int,
    grants: list[Any],
    idempotency_key: str,
    actor: ActorContextIn,
) -> dict[str, Any]:
    await _require(
        session, guild_id=guild_id, capability="chest.configure", actor=actor
    )
    action = "chest.catalog.publish"
    replay = await _receipt(
        session, guild_id=guild_id, idempotency_key=idempotency_key, action=action
    )
    if replay is not None:
        return dict(replay.result)
    draft = await get_or_create_draft(
        session, guild_id=guild_id, module_key=MODULE_KEY, for_update=True
    )
    if not grants:
        grants = _grants_from_chests(
            list(
                (
                    await session.execute(
                        select(ChestDraftChest).where(
                            ChestDraftChest.guild_id == guild_id,
                            ChestDraftChest.draft_id == draft.id,
                        )
                    )
                ).scalars()
            )
        )
    resource_ids = {
        value
        for value in (
            await session.execute(
                select(ChestDraftChest.chest_id).where(
                    ChestDraftChest.guild_id == guild_id,
                    ChestDraftChest.draft_id == draft.id,
                    ChestDraftChest.active.is_(True),
                )
            )
        ).scalars()
    }
    for grant in grants:
        if grant.scope_type == "resource" and grant.scope_id not in resource_ids:
            raise _http(
                422, "Grant por bau referencia recurso ausente ou inativo no draft."
            )
    version = await publish_configuration(
        session,
        guild_id=guild_id,
        module_key=MODULE_KEY,
        actor_id=_actor_id(actor),
        expected_revision=expected_revision,
        expected_published_version=expected_published_version,
        grants=grants,
        correlation_id=actor.correlation_id,
        commit=False,
    )
    result = {
        "id": version.id,
        "version": version.version,
        "schema_version": version.schema_version,
        "published_at": version.published_at,
    }
    _store_receipt(
        session,
        guild_id=guild_id,
        idempotency_key=idempotency_key,
        action=action,
        resource_id=str(version.id),
        result={
            **result,
            "published_at": version.published_at.isoformat()
            if version.published_at
            else None,
        },
    )
    await session.commit()
    return result


def _store_receipt(
    session: AsyncSession,
    *,
    guild_id: str,
    idempotency_key: str,
    action: str,
    resource_id: str,
    result: dict[str, Any],
) -> None:
    session.add(
        ChestCommandReceipt(
            guild_id=guild_id,
            idempotency_key=idempotency_key,
            action=action,
            resource_id=resource_id,
            result=result,
        )
    )


async def save_settings(
    session: AsyncSession,
    *,
    guild_id: str,
    expected_revision: int,
    expected_published_version: int,
    schema_version: int,
    data: dict[str, Any],
    idempotency_key: str,
    actor: ActorContextIn,
) -> dict[str, Any]:
    await _require(
        session, guild_id=guild_id, capability="chest.configure", actor=actor
    )
    action = "chest.config.update"
    replay = await _receipt(
        session, guild_id=guild_id, idempotency_key=idempotency_key, action=action
    )
    if replay is not None:
        return dict(replay.result)
    draft = await save_platform_draft(
        session,
        guild_id=guild_id,
        module_key=MODULE_KEY,
        actor_id=_actor_id(actor),
        expected_revision=expected_revision,
        expected_published_version=expected_published_version,
        schema_version=schema_version,
        data=data,
        correlation_id=actor.correlation_id,
        commit=False,
    )
    result = {
        "revision": draft.revision,
        "base_published_version": draft.base_published_version,
        "schema_version": draft.schema_version,
        "configuration": dict(draft.data or {}),
    }
    _store_receipt(
        session,
        guild_id=guild_id,
        idempotency_key=idempotency_key,
        action=action,
        resource_id=str(draft.id),
        result=result,
    )
    await session.commit()
    return result


def _chest_out(row: ChestDraftChest | ChestVersionChest) -> dict[str, Any]:
    def roles(name: str) -> list[str]:
        return list(getattr(row, name, None) or [])

    return {
        "id": row.chest_id,
        "name": row.name,
        "name_normalized": row.name_normalized,
        "description": getattr(row, "description", "") or "",
        "panel_channel_id": getattr(row, "panel_channel_id", None),
        "log_channel_id": getattr(row, "log_channel_id", None),
        "show_balances_to_members": getattr(row, "show_balances_to_members", True),
        "allow_personal_history": getattr(row, "allow_personal_history", True),
        "withdrawal_reason_required": getattr(row, "withdrawal_reason_required", True),
        "view_role_ids": roles("view_role_ids"),
        "deposit_role_ids": roles("deposit_role_ids"),
        "withdraw_role_ids": roles("withdraw_role_ids"),
        "admin_role_ids": roles("admin_role_ids"),
        "active": row.active,
        "position": row.position,
    }


def _item_out(row: ChestDraftItem | ChestVersionItem) -> dict[str, Any]:
    return {
        "id": row.item_id,
        "name": row.name,
        "name_normalized": row.name_normalized,
        "unit": row.unit,
        "active": row.active,
        "position": row.position,
    }


def _chest_settings(row: ChestDraftChest | ChestVersionChest, defaults: dict[str, Any]) -> dict[str, Any]:
    return {
        "panel_channel_id": getattr(row, "panel_channel_id", None) or defaults.get("panel_channel_id"),
        "log_channel_id": getattr(row, "log_channel_id", None) or defaults.get("log_channel_id"),
        "show_balances_to_members": getattr(row, "show_balances_to_members", None)
        if getattr(row, "show_balances_to_members", None) is not None
        else defaults.get("show_balances_to_members", True),
        "allow_personal_history": getattr(row, "allow_personal_history", None)
        if getattr(row, "allow_personal_history", None) is not None
        else defaults.get("allow_personal_history", True),
        "withdrawal_reason_required": getattr(row, "withdrawal_reason_required", None)
        if getattr(row, "withdrawal_reason_required", None) is not None
        else defaults.get("withdrawal_reason_required", True),
    }


async def catalog_draft(session: AsyncSession, *, guild_id: str) -> dict[str, Any]:
    draft = await get_or_create_draft(session, guild_id=guild_id, module_key=MODULE_KEY)
    chests = list(
        (
            await session.execute(
                select(ChestDraftChest)
                .where(
                    ChestDraftChest.guild_id == guild_id,
                    ChestDraftChest.draft_id == draft.id,
                )
                .order_by(ChestDraftChest.position, ChestDraftChest.name_normalized)
            )
        ).scalars()
    )
    items = list(
        (
            await session.execute(
                select(ChestDraftItem)
                .where(
                    ChestDraftItem.guild_id == guild_id,
                    ChestDraftItem.draft_id == draft.id,
                )
                .order_by(ChestDraftItem.position, ChestDraftItem.name_normalized)
            )
        ).scalars()
    )
    links = list(
        (
            await session.execute(
                select(ChestDraftLink).where(
                    ChestDraftLink.guild_id == guild_id,
                    ChestDraftLink.draft_id == draft.id,
                )
            )
        ).scalars()
    )
    return {
        "revision": draft.revision,
        "base_published_version": draft.base_published_version,
        "schema_version": draft.schema_version,
        "configuration": dict(draft.data or {}),
        "chests": [_chest_out(row) for row in chests],
        "items": [_item_out(row) for row in items],
        "links": [
            {"chest_id": row.chest_id, "item_id": row.item_id, "active": row.active}
            for row in links
        ],
    }


async def authorized_catalog_draft(
    session: AsyncSession, *, guild_id: str, actor: ActorContextIn
) -> dict[str, Any]:
    await _require(
        session, guild_id=guild_id, capability="chest.configure", actor=actor
    )
    return await catalog_draft(session, guild_id=guild_id)


async def _locked_draft(
    session: AsyncSession, *, guild_id: str, expected_revision: int
) -> ModuleConfigDraft:
    draft = await get_or_create_draft(
        session, guild_id=guild_id, module_key=MODULE_KEY, for_update=True
    )
    if draft.revision != expected_revision:
        raise _http(
            409,
            "Catalogo draft alterado por outra sessao.",
            current_revision=draft.revision,
        )
    return draft


def _advance(draft: ModuleConfigDraft, actor_id: str) -> None:
    draft.revision += 1
    draft.updated_by = actor_id
    draft.updated_at = datetime.now(timezone.utc)


async def upsert_draft_chest(
    session: AsyncSession,
    *,
    guild_id: str,
    chest_id: str | None,
    name: str,
    active: bool,
    position: int,
    expected_revision: int,
    idempotency_key: str,
    actor: ActorContextIn,
    description: str = "",
    panel_channel_id: str | None = None,
    log_channel_id: str | None = None,
    show_balances_to_members: bool = True,
    allow_personal_history: bool = True,
    withdrawal_reason_required: bool = True,
    view_role_ids: list[str] | None = None,
    deposit_role_ids: list[str] | None = None,
    withdraw_role_ids: list[str] | None = None,
    admin_role_ids: list[str] | None = None,
) -> dict[str, Any]:
    await _require(
        session, guild_id=guild_id, capability="chest.configure", actor=actor
    )
    action = "chest.catalog.chest_upsert"
    replay = await _receipt(
        session, guild_id=guild_id, idempotency_key=idempotency_key, action=action
    )
    if replay is not None:
        return dict(replay.result)
    draft = await _locked_draft(
        session, guild_id=guild_id, expected_revision=expected_revision
    )
    stable: Chest | None = None
    row: ChestDraftChest | None = None
    if chest_id:
        stable = (
            await session.execute(
                select(Chest).where(Chest.guild_id == guild_id, Chest.id == chest_id)
            )
        ).scalar_one_or_none()
        row = (
            await session.execute(
                select(ChestDraftChest).where(
                    ChestDraftChest.guild_id == guild_id,
                    ChestDraftChest.draft_id == draft.id,
                    ChestDraftChest.chest_id == chest_id,
                )
            )
        ).scalar_one_or_none()
        if stable is None or row is None:
            raise _http(404, "Bau nao encontrado neste draft.")
    else:
        stable = Chest(guild_id=guild_id, created_by=_actor_id(actor))
        session.add(stable)
        await session.flush()
        row = ChestDraftChest(
            draft_id=draft.id,
            guild_id=guild_id,
            chest_id=stable.id,
            name="",
            name_normalized="",
        )
        session.add(row)
    before = _chest_out(row) if row.name else {}
    row.name = compact_text(name, field="nome do bau", max_length=100)
    row.name_normalized = normalize_name(row.name)
    row.description = " ".join(description.strip().split())[:300]
    row.panel_channel_id = panel_channel_id or (draft.data or {}).get("panel_channel_id") or None
    row.log_channel_id = log_channel_id or (draft.data or {}).get("log_channel_id") or None
    row.show_balances_to_members = show_balances_to_members
    row.allow_personal_history = allow_personal_history
    row.withdrawal_reason_required = withdrawal_reason_required
    row.view_role_ids = list(view_role_ids or [])
    row.deposit_role_ids = list(deposit_role_ids or [])
    row.withdraw_role_ids = list(withdraw_role_ids or [])
    row.admin_role_ids = list(admin_role_ids or [])
    row.active = active
    row.position = position
    _advance(draft, _actor_id(actor))
    await session.flush()
    result = {**_chest_out(row), "revision": draft.revision}
    await write_audit(
        session,
        guild_id=guild_id,
        module_key=MODULE_KEY,
        action=action,
        resource_type="chest",
        resource_id=stable.id,
        actor_type=actor.actor_type,
        actor_id=actor.user_id,
        before=before,
        after=result,
        correlation_id=actor.correlation_id,
    )
    _store_receipt(
        session,
        guild_id=guild_id,
        idempotency_key=idempotency_key,
        action=action,
        resource_id=stable.id,
        result=result,
    )
    await session.commit()
    return result


async def upsert_draft_item(
    session: AsyncSession,
    *,
    guild_id: str,
    item_id: str | None,
    name: str,
    unit: str,
    active: bool,
    position: int,
    expected_revision: int,
    idempotency_key: str,
    actor: ActorContextIn,
) -> dict[str, Any]:
    await _require(
        session, guild_id=guild_id, capability="chest.configure", actor=actor
    )
    action = "chest.catalog.item_upsert"
    replay = await _receipt(
        session, guild_id=guild_id, idempotency_key=idempotency_key, action=action
    )
    if replay is not None:
        return dict(replay.result)
    draft = await _locked_draft(
        session, guild_id=guild_id, expected_revision=expected_revision
    )
    stable: ChestItem | None = None
    row: ChestDraftItem | None = None
    if item_id:
        stable = (
            await session.execute(
                select(ChestItem).where(
                    ChestItem.guild_id == guild_id, ChestItem.id == item_id
                )
            )
        ).scalar_one_or_none()
        row = (
            await session.execute(
                select(ChestDraftItem).where(
                    ChestDraftItem.guild_id == guild_id,
                    ChestDraftItem.draft_id == draft.id,
                    ChestDraftItem.item_id == item_id,
                )
            )
        ).scalar_one_or_none()
        if stable is None or row is None:
            raise _http(404, "Item nao encontrado neste draft.")
    else:
        stable = ChestItem(guild_id=guild_id, created_by=_actor_id(actor))
        session.add(stable)
        await session.flush()
        row = ChestDraftItem(
            draft_id=draft.id,
            guild_id=guild_id,
            item_id=stable.id,
            name="",
            name_normalized="",
            unit="unidade",
        )
        session.add(row)
    before = _item_out(row) if row.name else {}
    row.name = compact_text(name, field="nome do item", max_length=100)
    row.name_normalized = normalize_name(row.name)
    row.unit = compact_text(unit, field="unidade", max_length=40)
    row.active = active
    row.position = position
    _advance(draft, _actor_id(actor))
    await session.flush()
    result = {**_item_out(row), "revision": draft.revision}
    await write_audit(
        session,
        guild_id=guild_id,
        module_key=MODULE_KEY,
        action=action,
        resource_type="chest_item",
        resource_id=stable.id,
        actor_type=actor.actor_type,
        actor_id=actor.user_id,
        before=before,
        after=result,
        correlation_id=actor.correlation_id,
    )
    _store_receipt(
        session,
        guild_id=guild_id,
        idempotency_key=idempotency_key,
        action=action,
        resource_id=stable.id,
        result=result,
    )
    await session.commit()
    return result


async def upsert_draft_link(
    session: AsyncSession,
    *,
    guild_id: str,
    chest_id: str,
    item_id: str,
    active: bool,
    expected_revision: int,
    idempotency_key: str,
    actor: ActorContextIn,
) -> dict[str, Any]:
    await _require(
        session, guild_id=guild_id, capability="chest.configure", actor=actor
    )
    action = "chest.catalog.link_upsert"
    replay = await _receipt(
        session, guild_id=guild_id, idempotency_key=idempotency_key, action=action
    )
    if replay is not None:
        return dict(replay.result)
    draft = await _locked_draft(
        session, guild_id=guild_id, expected_revision=expected_revision
    )
    chest_row = (
        await session.execute(
            select(ChestDraftChest).where(
                ChestDraftChest.draft_id == draft.id,
                ChestDraftChest.guild_id == guild_id,
                ChestDraftChest.chest_id == chest_id,
            )
        )
    ).scalar_one_or_none()
    item_row = (
        await session.execute(
            select(ChestDraftItem).where(
                ChestDraftItem.draft_id == draft.id,
                ChestDraftItem.guild_id == guild_id,
                ChestDraftItem.item_id == item_id,
            )
        )
    ).scalar_one_or_none()
    if chest_row is None or item_row is None:
        raise _http(422, "O vinculo precisa usar bau e item do mesmo draft e guild.")
    row = (
        await session.execute(
            select(ChestDraftLink).where(
                ChestDraftLink.draft_id == draft.id,
                ChestDraftLink.guild_id == guild_id,
                ChestDraftLink.chest_id == chest_id,
                ChestDraftLink.item_id == item_id,
            )
        )
    ).scalar_one_or_none()
    before = {} if row is None else {"active": row.active}
    if row is None:
        row = ChestDraftLink(
            draft_id=draft.id,
            guild_id=guild_id,
            chest_id=chest_id,
            item_id=item_id,
            active=active,
        )
        session.add(row)
    else:
        row.active = active
    _advance(draft, _actor_id(actor))
    await session.flush()
    result = {
        "chest_id": chest_id,
        "item_id": item_id,
        "active": active,
        "revision": draft.revision,
    }
    await write_audit(
        session,
        guild_id=guild_id,
        module_key=MODULE_KEY,
        action=action,
        resource_type="chest_item_link",
        resource_id=f"{chest_id}:{item_id}",
        actor_type=actor.actor_type,
        actor_id=actor.user_id,
        before=before,
        after=result,
        correlation_id=actor.correlation_id,
    )
    _store_receipt(
        session,
        guild_id=guild_id,
        idempotency_key=idempotency_key,
        action=action,
        resource_id=f"{chest_id}:{item_id}",
        result=result,
    )
    await session.commit()
    return result


async def validate_catalog_draft(
    session: AsyncSession, *, guild_id: str, draft: ModuleConfigDraft
) -> list[str]:
    chests = list(
        (
            await session.execute(
                select(ChestDraftChest).where(
                    ChestDraftChest.guild_id == guild_id,
                    ChestDraftChest.draft_id == draft.id,
                    ChestDraftChest.active.is_(True),
                )
            )
        ).scalars()
    )
    items = list(
        (
            await session.execute(
                select(ChestDraftItem).where(
                    ChestDraftItem.guild_id == guild_id,
                    ChestDraftItem.draft_id == draft.id,
                    ChestDraftItem.active.is_(True),
                )
            )
        ).scalars()
    )
    links = list(
        (
            await session.execute(
                select(ChestDraftLink).where(
                    ChestDraftLink.guild_id == guild_id,
                    ChestDraftLink.draft_id == draft.id,
                    ChestDraftLink.active.is_(True),
                )
            )
        ).scalars()
    )
    errors: list[str] = []
    if not chests:
        errors.append("Cadastre ao menos um bau ativo.")
    if not items:
        errors.append("Cadastre ao menos um item ativo.")
    active_chests = {row.chest_id for row in chests}
    active_items = {row.item_id for row in items}
    valid_links = {
        (row.chest_id, row.item_id)
        for row in links
        if row.chest_id in active_chests and row.item_id in active_items
    }
    if not valid_links:
        errors.append("Associe ao menos um item ativo a um bau ativo.")
    defaults = dict(draft.data or {})
    for row in chests:
        if not (row.panel_channel_id or defaults.get("panel_channel_id")):
            errors.append(f"Selecione o canal do painel do bau '{row.name}'.")
        if not (row.log_channel_id or defaults.get("log_channel_id")):
            errors.append(f"Selecione o canal de logs do bau '{row.name}'.")
        if not any(
            link.chest_id == row.chest_id
            and link.item_id in active_items
            and link.active
            for link in links
        ):
            errors.append(f"Adicione ao menos um item ao bau '{row.name}'.")

    instance = await ensure_module_instance(
        session, guild_id=guild_id, module_key=MODULE_KEY
    )
    if instance.published_config_version_id:
        old = set(
            (
                await session.execute(
                    select(ChestVersionLink.chest_id, ChestVersionLink.item_id).where(
                        ChestVersionLink.guild_id == guild_id,
                        ChestVersionLink.config_version_id
                        == instance.published_config_version_id,
                        ChestVersionLink.active.is_(True),
                    )
                )
            ).all()
        )
        removed = old - valid_links
        if removed:
            nonzero = await session.scalar(
                select(func.count())
                .select_from(ChestBalance)
                .where(
                    ChestBalance.guild_id == guild_id,
                    tuple_(ChestBalance.chest_id, ChestBalance.item_id).in_(removed),
                    ChestBalance.quantity != 0,
                )
            )
            if nonzero:
                errors.append(
                    "Zere os saldos antes de remover ou desativar vinculos publicados."
                )
    return errors


async def materialize_catalog_version(
    session: AsyncSession,
    *,
    guild_id: str,
    draft: ModuleConfigDraft,
    version: ModuleConfigVersion,
) -> None:
    chests = list(
        (
            await session.execute(
                select(ChestDraftChest).where(
                    ChestDraftChest.guild_id == guild_id,
                    ChestDraftChest.draft_id == draft.id,
                )
            )
        ).scalars()
    )
    items = list(
        (
            await session.execute(
                select(ChestDraftItem).where(
                    ChestDraftItem.guild_id == guild_id,
                    ChestDraftItem.draft_id == draft.id,
                )
            )
        ).scalars()
    )
    links = list(
        (
            await session.execute(
                select(ChestDraftLink).where(
                    ChestDraftLink.guild_id == guild_id,
                    ChestDraftLink.draft_id == draft.id,
                )
            )
        ).scalars()
    )
    active_chests = {row.chest_id for row in chests if row.active}
    active_items = {row.item_id for row in items if row.active}
    new_active = {
        (row.chest_id, row.item_id)
        for row in links
        if row.active and row.chest_id in active_chests and row.item_id in active_items
    }
    instance = await ensure_module_instance(
        session, guild_id=guild_id, module_key=MODULE_KEY, for_update=True
    )
    # O contrato antigo publicava um singleton global. Ao cortar para paineis
    # por bau, ele deixa de ser uma instancia operacional valida.
    await session.execute(
        update(PanelInstance)
        .where(
            PanelInstance.guild_id == guild_id,
            PanelInstance.module_key == MODULE_KEY,
            PanelInstance.panel_key == "global",
            PanelInstance.state == PanelState.published,
        )
        .values(
            state=PanelState.paused,
            last_error="Painel global substituido por paineis individuais de cada bau.",
        )
    )
    old_active: set[tuple[str, str]] = set()
    if instance.published_config_version_id:
        old_active = set(
            (
                await session.execute(
                    select(ChestVersionLink.chest_id, ChestVersionLink.item_id).where(
                        ChestVersionLink.guild_id == guild_id,
                        ChestVersionLink.config_version_id
                        == instance.published_config_version_id,
                        ChestVersionLink.active.is_(True),
                    )
                )
            ).all()
        )
    affected = sorted(old_active - new_active)
    if affected:
        balances = list(
            (
                await session.execute(
                    select(ChestBalance)
                    .where(
                        ChestBalance.guild_id == guild_id,
                        tuple_(ChestBalance.chest_id, ChestBalance.item_id).in_(
                            affected
                        ),
                    )
                    .order_by(ChestBalance.chest_id, ChestBalance.item_id)
                    .with_for_update()
                )
            ).scalars()
        )
        if any(Decimal(row.quantity) != 0 for row in balances):
            raise _http(
                409,
                "Publicacao bloqueada: existe saldo em vinculo removido ou inativo.",
            )

    for row in chests:
        session.add(
            ChestVersionChest(
                config_version_id=version.id,
                guild_id=guild_id,
                chest_id=row.chest_id,
                name=row.name,
                name_normalized=row.name_normalized,
                description=row.description,
                panel_channel_id=row.panel_channel_id or (draft.data or {}).get("panel_channel_id"),
                log_channel_id=row.log_channel_id or (draft.data or {}).get("log_channel_id"),
                show_balances_to_members=row.show_balances_to_members,
                allow_personal_history=row.allow_personal_history,
                withdrawal_reason_required=row.withdrawal_reason_required,
                view_role_ids=list(row.view_role_ids or []),
                deposit_role_ids=list(row.deposit_role_ids or []),
                withdraw_role_ids=list(row.withdraw_role_ids or []),
                admin_role_ids=list(row.admin_role_ids or []),
                active=row.active,
                position=row.position,
            )
        )
    for row in items:
        session.add(
            ChestVersionItem(
                config_version_id=version.id,
                guild_id=guild_id,
                item_id=row.item_id,
                name=row.name,
                name_normalized=row.name_normalized,
                unit=row.unit,
                active=row.active,
                position=row.position,
            )
        )
    for row in links:
        session.add(
            ChestVersionLink(
                config_version_id=version.id,
                guild_id=guild_id,
                chest_id=row.chest_id,
                item_id=row.item_id,
                active=row.active
                and row.chest_id in active_chests
                and row.item_id in active_items,
            )
        )
    existing = (
        set(
            (
                await session.execute(
                    select(ChestBalance.chest_id, ChestBalance.item_id).where(
                        ChestBalance.guild_id == guild_id,
                        tuple_(ChestBalance.chest_id, ChestBalance.item_id).in_(
                            new_active
                        ),
                    )
                )
            ).all()
        )
        if new_active
        else set()
    )
    for chest_id, item_id in sorted(new_active - existing):
        session.add(ChestBalance(guild_id=guild_id, chest_id=chest_id, item_id=item_id))
    await session.flush()
    config = dict(draft.data or {})
    for row in chests:
        if not row.active:
            continue
        destination_id = row.panel_channel_id or config.get("panel_channel_id")
        if not destination_id:
            continue
        await enqueue_delivery(
            session,
            guild_id=guild_id,
            module_key=MODULE_KEY,
            renderer_key="chest.panel",
            destination_type="channel",
            destination_id=str(destination_id),
            resource_type="chest",
            resource_id=row.chest_id,
            payload={"config_version": version.version, "chest_id": row.chest_id},
            priority=40,
            available_at=datetime.now(timezone.utc),
            idempotency_key=f"chest:panel:{guild_id}:version:{version.version}:chest:{row.chest_id}",
            correlation_id=f"chest-publish:{guild_id}:{version.version}:{row.chest_id}",
            max_attempts=5,
            commit=False,
        )


async def restore_catalog_version(
    session: AsyncSession,
    *,
    guild_id: str,
    draft: ModuleConfigDraft,
    source: ModuleConfigVersion,
) -> None:
    await session.execute(
        delete(ChestDraftLink).where(
            ChestDraftLink.draft_id == draft.id, ChestDraftLink.guild_id == guild_id
        )
    )
    await session.execute(
        delete(ChestDraftChest).where(
            ChestDraftChest.draft_id == draft.id, ChestDraftChest.guild_id == guild_id
        )
    )
    await session.execute(
        delete(ChestDraftItem).where(
            ChestDraftItem.draft_id == draft.id, ChestDraftItem.guild_id == guild_id
        )
    )
    await session.flush()
    source_chests = list(
        (
            await session.execute(
                select(ChestVersionChest).where(
                    ChestVersionChest.guild_id == guild_id,
                    ChestVersionChest.config_version_id == source.id,
                )
            )
        ).scalars()
    )
    source_items = list(
        (
            await session.execute(
                select(ChestVersionItem).where(
                    ChestVersionItem.guild_id == guild_id,
                    ChestVersionItem.config_version_id == source.id,
                )
            )
        ).scalars()
    )
    source_links = list(
        (
            await session.execute(
                select(ChestVersionLink).where(
                    ChestVersionLink.guild_id == guild_id,
                    ChestVersionLink.config_version_id == source.id,
                )
            )
        ).scalars()
    )
    for row in source_chests:
        session.add(
            ChestDraftChest(
                draft_id=draft.id,
                guild_id=guild_id,
                chest_id=row.chest_id,
                name=row.name,
                name_normalized=row.name_normalized,
                description=getattr(row, "description", "") or "",
                panel_channel_id=getattr(row, "panel_channel_id", None),
                log_channel_id=getattr(row, "log_channel_id", None),
                show_balances_to_members=getattr(row, "show_balances_to_members", True),
                allow_personal_history=getattr(row, "allow_personal_history", True),
                withdrawal_reason_required=getattr(row, "withdrawal_reason_required", True),
                view_role_ids=list(getattr(row, "view_role_ids", None) or []),
                deposit_role_ids=list(getattr(row, "deposit_role_ids", None) or []),
                withdraw_role_ids=list(getattr(row, "withdraw_role_ids", None) or []),
                admin_role_ids=list(getattr(row, "admin_role_ids", None) or []),
                active=row.active,
                position=row.position,
            )
        )
    for row in source_items:
        session.add(
            ChestDraftItem(
                draft_id=draft.id,
                guild_id=guild_id,
                item_id=row.item_id,
                name=row.name,
                name_normalized=row.name_normalized,
                unit=row.unit,
                active=row.active,
                position=row.position,
            )
        )
    await session.flush()
    for row in source_links:
        session.add(
            ChestDraftLink(
                draft_id=draft.id,
                guild_id=guild_id,
                chest_id=row.chest_id,
                item_id=row.item_id,
                active=row.active,
            )
        )
    await session.flush()


async def published_catalog(session: AsyncSession, *, guild_id: str) -> dict[str, Any]:
    instance = await ensure_module_instance(
        session, guild_id=guild_id, module_key=MODULE_KEY
    )
    version_id = instance.published_config_version_id
    if version_id is None:
        raise _http(404, "Modulo sem catalogo publicado.")
    version = await session.get(ModuleConfigVersion, version_id)
    chests = list(
        (
            await session.execute(
                select(ChestVersionChest)
                .where(
                    ChestVersionChest.guild_id == guild_id,
                    ChestVersionChest.config_version_id == version_id,
                )
                .order_by(ChestVersionChest.position, ChestVersionChest.name_normalized)
            )
        ).scalars()
    )
    items = list(
        (
            await session.execute(
                select(ChestVersionItem)
                .where(
                    ChestVersionItem.guild_id == guild_id,
                    ChestVersionItem.config_version_id == version_id,
                )
                .order_by(ChestVersionItem.position, ChestVersionItem.name_normalized)
            )
        ).scalars()
    )
    links = list(
        (
            await session.execute(
                select(ChestVersionLink).where(
                    ChestVersionLink.guild_id == guild_id,
                    ChestVersionLink.config_version_id == version_id,
                )
            )
        ).scalars()
    )
    chest_output = [_chest_out(row) for row in chests]
    item_counts: dict[str, int] = {}
    for link in links:
        if link.active:
            item_counts[link.chest_id] = item_counts.get(link.chest_id, 0) + 1
    for chest in chest_output:
        chest["item_count"] = item_counts.get(chest["id"], 0)
    return {
        "version": version.version if version else 0,
        "configuration": dict(version.data or {}) if version else {},
        "chests": chest_output,
        "items": [_item_out(row) for row in items],
        "links": [
            {"chest_id": row.chest_id, "item_id": row.item_id, "active": row.active}
            for row in links
        ],
    }


async def authorized_catalog(
    session: AsyncSession, *, guild_id: str, actor: ActorContextIn
) -> dict[str, Any]:
    catalog = await published_catalog(session, guild_id=guild_id)
    allowed_chests: list[dict[str, Any]] = []
    for chest in catalog["chests"]:
        if not chest["active"]:
            continue
        if actor.actor_type == "system":
            allowed_chests.append(chest)
            continue
        decision = await authorize(
            session,
            guild_id=guild_id,
            module_key=MODULE_KEY,
            capability_key="chest.view",
            actor=actor,
            resource_id=chest["id"],
        )
        if decision.allowed:
            allowed_chests.append(chest)
    allowed_ids = {item["id"] for item in allowed_chests}
    return {
        "version": catalog["version"],
        "configuration": catalog["configuration"],
        "chests": allowed_chests,
        "items": catalog["items"],
        "links": [
            row
            for row in catalog["links"]
            if row["chest_id"] in allowed_ids and row["active"]
        ],
    }


async def _published_link(
    session: AsyncSession,
    *,
    guild_id: str,
    version_id: int,
    chest_id: str,
    item_id: str,
) -> tuple[ChestVersionChest, ChestVersionItem] | None:
    row = (
        await session.execute(
            select(ChestVersionChest, ChestVersionItem)
            .join(
                ChestVersionLink,
                (
                    ChestVersionLink.config_version_id
                    == ChestVersionChest.config_version_id
                )
                & (ChestVersionLink.guild_id == ChestVersionChest.guild_id)
                & (ChestVersionLink.chest_id == ChestVersionChest.chest_id),
            )
            .join(
                ChestVersionItem,
                (
                    ChestVersionItem.config_version_id
                    == ChestVersionLink.config_version_id
                )
                & (ChestVersionItem.guild_id == ChestVersionLink.guild_id)
                & (ChestVersionItem.item_id == ChestVersionLink.item_id),
            )
            .where(
                ChestVersionLink.guild_id == guild_id,
                ChestVersionLink.config_version_id == version_id,
                ChestVersionLink.chest_id == chest_id,
                ChestVersionLink.item_id == item_id,
                ChestVersionLink.active.is_(True),
                ChestVersionChest.active.is_(True),
                ChestVersionItem.active.is_(True),
            )
        )
    ).first()
    return (row[0], row[1]) if row else None


MOVEMENT_CAPABILITIES = {
    MovementType.DEPOSIT: "chest.deposit",
    MovementType.WITHDRAWAL: "chest.withdraw",
    MovementType.ADJUSTMENT_CREDIT: "chest.adjust",
    MovementType.ADJUSTMENT_DEBIT: "chest.adjust",
}


def movement_out(row: ChestMovement) -> dict[str, Any]:
    return {
        "id": row.id,
        "guild_id": row.guild_id,
        "chest_id": row.chest_id,
        "item_id": row.item_id,
        "movement_type": row.movement_type.value,
        "quantity": str(row.quantity),
        "actor_id": row.actor_id,
        "actor_type": row.actor_type,
        "balance_before": str(row.balance_before),
        "balance_after": str(row.balance_after),
        "sequence": row.sequence,
        "observation": row.observation,
        "correlation_id": row.correlation_id,
        "idempotency_key": row.idempotency_key,
        "origin": row.origin,
        "chest_name": row.chest_name_snapshot,
        "item_name": row.item_name_snapshot,
        "unit": row.unit_snapshot,
        "created_at": row.created_at,
    }


async def record_movement(
    session: AsyncSession,
    *,
    guild_id: str,
    chest_id: str,
    item_id: str,
    movement_type: MovementType,
    amount: Decimal,
    observation: str | None,
    idempotency_key: str,
    origin: str,
    actor: ActorContextIn,
    capability_override: str | None = None,
) -> ChestMovement:
    kind = MovementType(movement_type)
    await _require(
        session,
        guild_id=guild_id,
        capability=capability_override or MOVEMENT_CAPABILITIES[kind],
        actor=actor,
        resource_id=chest_id,
    )
    amount = quantity(amount)
    instance = await ensure_module_instance(
        session, guild_id=guild_id, module_key=MODULE_KEY, for_update=True
    )
    existing = (
        await session.execute(
            select(ChestMovement).where(
                ChestMovement.guild_id == guild_id,
                ChestMovement.idempotency_key == idempotency_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.chest_id != chest_id
            or existing.item_id != item_id
            or existing.movement_type != kind
            or Decimal(existing.quantity) != amount
        ):
            raise _http(
                409, "A chave de idempotencia ja foi usada por outra movimentacao."
            )
        return existing
    if instance.published_config_version_id is None:
        raise _http(409, "Modulo sem catalogo publicado.")
    balance = (
        await session.execute(
            select(ChestBalance)
            .where(
                ChestBalance.guild_id == guild_id,
                ChestBalance.chest_id == chest_id,
                ChestBalance.item_id == item_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if balance is None:
        raise _http(409, "Saldo materializado ausente para este vinculo.")
    link = await _published_link(
        session,
        guild_id=guild_id,
        version_id=instance.published_config_version_id,
        chest_id=chest_id,
        item_id=item_id,
    )
    if link is None:
        raise _http(409, "Bau e item nao possuem vinculo publicado ativo.")
    chest_row, item_row = link
    version = await session.get(
        ModuleConfigVersion, instance.published_config_version_id
    )
    config = dict(version.data or {}) if version else {}
    settings = _chest_settings(chest_row, config)
    if kind == MovementType.WITHDRAWAL and settings["withdrawal_reason_required"] and not observation:
        raise _http(422, "O motivo da retirada e obrigatorio.")
    before = Decimal(balance.quantity)
    try:
        after = apply_movement(before, kind, amount)
    except ValueError as exc:
        raise _http(409, str(exc)) from exc
    balance.quantity = after
    balance.sequence += 1
    movement = ChestMovement(
        guild_id=guild_id,
        balance_id=balance.id,
        chest_id=chest_id,
        item_id=item_id,
        movement_type=kind,
        quantity=amount,
        actor_id=_actor_id(actor),
        actor_type=actor.actor_type,
        balance_before=before,
        balance_after=after,
        sequence=balance.sequence,
        observation=observation,
        correlation_id=actor.correlation_id,
        idempotency_key=idempotency_key,
        origin=compact_text(origin, field="origem", max_length=64),
        chest_name_snapshot=chest_row.name,
        item_name_snapshot=item_row.name,
        unit_snapshot=item_row.unit,
    )
    session.add(movement)
    await session.flush()
    await write_audit(
        session,
        guild_id=guild_id,
        module_key=MODULE_KEY,
        action=f"chest.movement.{kind.value.lower()}",
        resource_type="chest_movement",
        resource_id=movement.id,
        actor_type=actor.actor_type,
        actor_id=actor.user_id,
        before={"balance": str(before), "sequence": balance.sequence - 1},
        after={
            "balance": str(after),
            "sequence": balance.sequence,
            "quantity": str(amount),
        },
        config_version=version.version if version else None,
        correlation_id=actor.correlation_id,
        metadata={"chest_id": chest_id, "item_id": item_id, "origin": origin},
    )
    await enqueue_delivery(
        session,
        guild_id=guild_id,
        module_key=MODULE_KEY,
        renderer_key="chest.log",
        destination_type="channel",
        destination_id=str(settings["log_channel_id"] or ""),
        resource_type="chest_movement",
        resource_id=movement.id,
        payload={
            "movement_id": movement.id,
            "movement_type": kind.value,
            "quantity": str(amount),
            "balance_before": str(before),
            "balance_after": str(after),
            "actor_id": movement.actor_id,
            "chest_name": chest_row.name,
            "item_name": item_row.name,
            "unit": item_row.unit,
            "observation": observation,
        },
        priority=50,
        available_at=datetime.now(timezone.utc),
        idempotency_key=f"chest:movement:{movement.id}:log",
        correlation_id=actor.correlation_id,
        max_attempts=8,
        commit=False,
    )
    await session.commit()
    return movement


async def record_external_deposit(
    session: AsyncSession,
    *,
    guild_id: str,
    source_module: str,
    source_event_id: str,
    chest_id: str,
    item_id: str,
    amount: Decimal,
    observation: str | None,
    actor: ActorContextIn,
) -> ChestMovement:
    idempotency_key = f"{source_module}:{source_event_id}"
    if len(idempotency_key) > 160:
        raise _http(422, "A chave externa de idempotencia excede 160 caracteres.")
    return await record_movement(
        session,
        guild_id=guild_id,
        chest_id=chest_id,
        item_id=item_id,
        movement_type=MovementType.DEPOSIT,
        amount=amount,
        observation=observation,
        idempotency_key=idempotency_key,
        origin=source_module,
        actor=actor,
        capability_override="chest.automation",
    )


async def stock(
    session: AsyncSession, *, guild_id: str, chest_id: str, actor: ActorContextIn
) -> dict[str, Any]:
    permissions = [
        await authorize(
            session,
            guild_id=guild_id,
            module_key=MODULE_KEY,
            capability_key=capability,
            actor=actor,
            resource_id=chest_id,
        )
        for capability in ("chest.view", "chest.deposit", "chest.withdraw")
    ]
    if not any(permission.allowed for permission in permissions):
        raise _http(403, "Sem permissao para consultar este bau.")
    instance = await ensure_module_instance(
        session, guild_id=guild_id, module_key=MODULE_KEY
    )
    if instance.published_config_version_id is None:
        raise _http(404, "Modulo sem catalogo publicado.")
    chest_row = (
        await session.execute(
            select(ChestVersionChest).where(
                ChestVersionChest.guild_id == guild_id,
                ChestVersionChest.config_version_id
                == instance.published_config_version_id,
                ChestVersionChest.chest_id == chest_id,
                ChestVersionChest.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if chest_row is None:
        raise _http(404, "Bau publicado nao encontrado.")
    rows = (
        await session.execute(
            select(ChestVersionItem, ChestBalance)
            .join(
                ChestVersionLink,
                (
                    ChestVersionLink.config_version_id
                    == ChestVersionItem.config_version_id
                )
                & (ChestVersionLink.guild_id == ChestVersionItem.guild_id)
                & (ChestVersionLink.item_id == ChestVersionItem.item_id),
            )
            .join(
                ChestBalance,
                (ChestBalance.guild_id == ChestVersionLink.guild_id)
                & (ChestBalance.chest_id == ChestVersionLink.chest_id)
                & (ChestBalance.item_id == ChestVersionLink.item_id),
            )
            .where(
                ChestVersionLink.guild_id == guild_id,
                ChestVersionLink.config_version_id
                == instance.published_config_version_id,
                ChestVersionLink.chest_id == chest_id,
                ChestVersionLink.active.is_(True),
                ChestVersionItem.active.is_(True),
            )
            .order_by(ChestVersionItem.position, ChestVersionItem.name_normalized)
        )
    ).all()
    version = await session.get(
        ModuleConfigVersion, instance.published_config_version_id
    )
    settings = _chest_settings(chest_row, dict(version.data or {}) if version else {})
    show = bool(settings["show_balances_to_members"])
    reason_required = bool(settings["withdrawal_reason_required"])
    if not show:
        withdraw = await authorize(
            session,
            guild_id=guild_id,
            module_key=MODULE_KEY,
            capability_key="chest.withdraw",
            actor=actor,
            resource_id=chest_id,
        )
        show = withdraw.allowed
    return {
        "chest": _chest_out(chest_row),
        "show_balances": show,
        "withdrawal_reason_required": reason_required,
        "items": [
            {
                **_item_out(item),
                "quantity": str(balance.quantity) if show else None,
                "sequence": balance.sequence,
            }
            for item, balance in rows
        ],
    }


async def history(
    session: AsyncSession,
    *,
    guild_id: str,
    actor: ActorContextIn,
    chest_id: str | None = None,
    item_id: str | None = None,
    actor_id: str | None = None,
    limit: int = 25,
    before_sequence: int | None = None,
) -> list[ChestMovement]:
    own = actor_id is not None and actor_id == actor.user_id
    capability = "chest.history_own" if own else "chest.history"
    await _require(
        session,
        guild_id=guild_id,
        capability=capability,
        actor=actor,
        resource_id=chest_id or "",
    )
    if own:
        instance = await ensure_module_instance(
            session, guild_id=guild_id, module_key=MODULE_KEY
        )
        version = (
            await session.get(ModuleConfigVersion, instance.published_config_version_id)
            if instance.published_config_version_id
            else None
        )
        allow_history = bool((version.data or {}).get("allow_personal_history", True)) if version else True
        if version is not None and chest_id:
            chest_config = await session.scalar(
                select(ChestVersionChest.allow_personal_history).where(
                    ChestVersionChest.guild_id == guild_id,
                    ChestVersionChest.config_version_id == version.id,
                    ChestVersionChest.chest_id == chest_id,
                )
            )
            if chest_config is not None:
                allow_history = bool(chest_config)
        if version is None or not allow_history:
            raise _http(
                403, "Historico pessoal desabilitado na configuracao publicada."
            )
    query = select(ChestMovement).where(ChestMovement.guild_id == guild_id)
    if chest_id:
        query = query.where(ChestMovement.chest_id == chest_id)
    if item_id:
        query = query.where(ChestMovement.item_id == item_id)
    if actor_id:
        query = query.where(ChestMovement.actor_id == actor_id)
    if before_sequence:
        query = query.where(ChestMovement.sequence < before_sequence)
    return list(
        (
            await session.execute(
                query.order_by(
                    ChestMovement.created_at.desc(), ChestMovement.id.desc()
                ).limit(limit)
            )
        ).scalars()
    )


async def create_missing_balances(
    session: AsyncSession,
    *,
    guild_id: str,
    actor: ActorContextIn,
    idempotency_key: str,
    chest_id: str | None = None,
) -> dict[str, Any]:
    await _require(session, guild_id=guild_id, capability="chest.recover", actor=actor)
    action = "chest.recovery.create_missing_balances"
    replay = await _receipt(
        session, guild_id=guild_id, idempotency_key=idempotency_key, action=action
    )
    if replay is not None:
        return dict(replay.result)
    instance = await ensure_module_instance(
        session, guild_id=guild_id, module_key=MODULE_KEY, for_update=True
    )
    if instance.published_config_version_id is None:
        raise _http(409, "Modulo sem catalogo publicado.")
    active_query = select(ChestVersionLink.chest_id, ChestVersionLink.item_id).where(
        ChestVersionLink.guild_id == guild_id,
        ChestVersionLink.config_version_id == instance.published_config_version_id,
        ChestVersionLink.active.is_(True),
    )
    if chest_id:
        active_query = active_query.where(ChestVersionLink.chest_id == chest_id)
    active = set(
        (
            await session.execute(active_query)
        ).all()
    )
    existing = set(
        (
            await session.execute(
                select(ChestBalance.chest_id, ChestBalance.item_id).where(
                    ChestBalance.guild_id == guild_id
                )
            )
        ).all()
    )
    missing = sorted(active - existing)
    for chest_id, item_id in missing:
        session.add(ChestBalance(guild_id=guild_id, chest_id=chest_id, item_id=item_id))
    await session.flush()
    result = {"created": len(missing), "missing": 0}
    await write_audit(
        session,
        guild_id=guild_id,
        module_key=MODULE_KEY,
        action=action,
        resource_type="chest_catalog",
        actor_type=actor.actor_type,
        actor_id=actor.user_id,
        after=result,
        correlation_id=actor.correlation_id,
    )
    _store_receipt(
        session,
        guild_id=guild_id,
        idempotency_key=idempotency_key,
        action=action,
        resource_id=chest_id or guild_id,
        result=result,
    )
    await session.commit()
    return result


async def queue_panel_recovery(
    session: AsyncSession,
    *,
    guild_id: str,
    actor: ActorContextIn,
    idempotency_key: str,
    chest_id: str | None = None,
) -> dict[str, Any]:
    await _require(session, guild_id=guild_id, capability="chest.recover", actor=actor)
    action = "chest.recovery.reconcile_panel"
    replay = await _receipt(
        session, guild_id=guild_id, idempotency_key=idempotency_key, action=action
    )
    if replay is not None:
        return dict(replay.result)
    instance = await ensure_module_instance(
        session, guild_id=guild_id, module_key=MODULE_KEY, for_update=True
    )
    version = (
        await session.get(ModuleConfigVersion, instance.published_config_version_id)
        if instance.published_config_version_id
        else None
    )
    if version is None:
        raise _http(409, "Modulo sem configuracao publicada.")
    if not chest_id:
        raise _http(422, "Informe qual bau deve ser recuperado.")
    chest_row = await session.scalar(
        select(ChestVersionChest).where(
            ChestVersionChest.guild_id == guild_id,
            ChestVersionChest.config_version_id == version.id,
            ChestVersionChest.chest_id == chest_id,
            ChestVersionChest.active.is_(True),
        )
    )
    if chest_row is None:
        raise _http(404, "Bau publicado nao encontrado.")
    destination_id = str(
        chest_row.panel_channel_id or (version.data or {}).get("panel_channel_id") or ""
    )
    if not destination_id:
        raise _http(422, "Canal do painel ausente na configuracao publicada.")
    delivery = await enqueue_delivery(
        session,
        guild_id=guild_id,
        module_key=MODULE_KEY,
        renderer_key="chest.panel",
        destination_type="channel",
        destination_id=destination_id,
        resource_type="chest",
        resource_id=chest_id,
        payload={"config_version": version.version, "chest_id": chest_id, "reason": "recovery"},
        priority=20,
        available_at=datetime.now(timezone.utc),
        idempotency_key="chest:panel:recovery:"
        + hashlib.sha256(idempotency_key.encode()).hexdigest(),
        correlation_id=actor.correlation_id,
        max_attempts=5,
        commit=False,
    )
    result = {"action": "reconcile_panel", "queued": True, "delivery_id": delivery.id}
    await write_audit(
        session,
        guild_id=guild_id,
        module_key=MODULE_KEY,
        action=action,
        resource_type="panel",
        resource_id=chest_id,
        actor_type=actor.actor_type,
        actor_id=actor.user_id,
        after=result,
        correlation_id=actor.correlation_id,
    )
    _store_receipt(
        session,
        guild_id=guild_id,
        idempotency_key=idempotency_key,
        action=action,
        resource_id=chest_id,
        result=result,
    )
    await session.commit()
    return result


async def record_resource_deleted(
    session: AsyncSession,
    *,
    guild_id: str,
    resource_type: str,
    resource_id: str,
    idempotency_key: str,
    actor: ActorContextIn,
) -> dict[str, Any]:
    await _require(
        session, guild_id=guild_id, capability="chest.automation", actor=actor
    )
    action = "chest.runtime.resource_deleted"
    replay = await _receipt(
        session, guild_id=guild_id, idempotency_key=idempotency_key, action=action
    )
    if replay is not None:
        return dict(replay.result)
    query = select(PanelInstance).where(
        PanelInstance.guild_id == guild_id,
        PanelInstance.module_key == MODULE_KEY,
        PanelInstance.panel_key == "chest",
    )
    if resource_type == "message":
        query = query.where(PanelInstance.message_id == resource_id)
    else:
        query = query.where(PanelInstance.channel_id == resource_id)
    panels = list((await session.execute(query.with_for_update())).scalars())
    result = {"affected": bool(panels), "affected_count": len(panels), "recovery_queued": False}
    instance = await ensure_module_instance(session, guild_id=guild_id, module_key=MODULE_KEY) if panels else None
    version = (
        await session.get(ModuleConfigVersion, instance.published_config_version_id)
        if instance and instance.published_config_version_id
        else None
    )
    for panel in panels:
        panel.state = PanelState.missing
        panel.render_revision += 1
        panel.last_error = f"Recurso Discord removido: {resource_type}:{resource_id}"
        chest_row = (
            await session.scalar(
                select(ChestVersionChest).where(
                    ChestVersionChest.guild_id == guild_id,
                    ChestVersionChest.config_version_id == version.id,
                    ChestVersionChest.chest_id == panel.resource_id,
                )
            )
            if version
            else None
        )
        destination_id = str(
            chest_row.panel_channel_id or (version.data or {}).get("panel_channel_id") or ""
        ) if chest_row and version else ""
        if version and destination_id and not (
            resource_type in {"channel", "thread"} and destination_id == resource_id
        ):
            await enqueue_delivery(
                session,
                guild_id=guild_id,
                module_key=MODULE_KEY,
                renderer_key="chest.panel",
                destination_type="channel",
                destination_id=destination_id,
                resource_type="chest",
                resource_id=panel.resource_id,
                payload={"reason": "discord_resource_deleted", "chest_id": panel.resource_id},
                priority=10,
                available_at=datetime.now(timezone.utc),
                idempotency_key="chest:deleted:"
                + hashlib.sha256(f"{idempotency_key}:{panel.resource_id}".encode()).hexdigest(),
                correlation_id=actor.correlation_id,
                max_attempts=5,
                commit=False,
            )
            result["recovery_queued"] = True
    await write_audit(
        session,
        guild_id=guild_id,
        module_key=MODULE_KEY,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_type=actor.actor_type,
        actor_id=actor.user_id,
        after=result,
        correlation_id=actor.correlation_id,
    )
    _store_receipt(
        session,
        guild_id=guild_id,
        idempotency_key=idempotency_key,
        action=action,
        resource_id=resource_id,
        result=result,
    )
    await session.commit()
    return result


async def diagnostics(session: AsyncSession, *, guild_id: str) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    instance = await ensure_module_instance(
        session, guild_id=guild_id, module_key=MODULE_KEY
    )
    checks: list[dict[str, Any]] = []
    version = (
        await session.get(ModuleConfigVersion, instance.published_config_version_id)
        if instance.published_config_version_id
        else None
    )
    checks.append(
        {
            "status": "OK" if version else "ERROR",
            "code": "chest.configuration",
            "summary": "Configuracao publicada presente."
            if version
            else "Configuracao publicada ausente.",
            "detail": "",
            "action": "Publique a configuracao e o catalogo." if not version else "",
            "checked_at": now,
        }
    )
    published_chests: list[ChestVersionChest] = []
    if version:
        config = dict(version.data or {})
        published_chests = list(
            (
                await session.execute(
                    select(ChestVersionChest).where(
                        ChestVersionChest.guild_id == guild_id,
                        ChestVersionChest.config_version_id == version.id,
                        ChestVersionChest.active.is_(True),
                    )
                )
            ).scalars()
        )
        channels_valid = bool(published_chests) and all(
            _chest_settings(row, config)["panel_channel_id"]
            and _chest_settings(row, config)["log_channel_id"]
            for row in published_chests
        )
        checks.append(
            {
                "status": "OK" if channels_valid else "ERROR",
                "code": "chest.channels",
                "summary": "Canais operacionais configurados."
                if channels_valid
                else "Canal do painel ou de logs ausente.",
                "detail": "",
                "action": "Revise os canais no draft." if not channels_valid else "",
                "checked_at": now,
            }
        )
        active_links = set(
            (
                await session.execute(
                    select(ChestVersionLink.chest_id, ChestVersionLink.item_id).where(
                        ChestVersionLink.guild_id == guild_id,
                        ChestVersionLink.config_version_id == version.id,
                        ChestVersionLink.active.is_(True),
                    )
                )
            ).all()
        )
        balance_links = set(
            (
                await session.execute(
                    select(ChestBalance.chest_id, ChestBalance.item_id).where(
                        ChestBalance.guild_id == guild_id
                    )
                )
            ).all()
        )
        missing = len(active_links - balance_links)
        checks.append(
            {
                "status": "ERROR" if missing else "OK",
                "code": "chest.balances",
                "summary": f"{missing} vinculo(s) publicado(s) sem saldo materializado."
                if missing
                else "Saldos materializados consistentes.",
                "detail": "",
                "action": "Execute a recuperacao de saldos." if missing else "",
                "checked_at": now,
            }
        )
    panels = list(
        (
            await session.execute(
                select(PanelInstance).where(
                    PanelInstance.guild_id == guild_id,
                    PanelInstance.module_key == MODULE_KEY,
                    PanelInstance.panel_key == "chest",
                )
            )
        ).scalars()
    )
    panel_by_chest = {panel.resource_id: panel for panel in panels}
    panel_ok = bool(version) and bool(published_chests) and all(
        (panel := panel_by_chest.get(row.chest_id)) is not None
        and panel.state.value == "published"
        and bool(panel.channel_id and panel.message_id)
        for row in published_chests
    )
    panel_errors = [panel.last_error for panel in panels if panel.last_error]
    checks.append(
        {
            "status": "OK" if panel_ok else "WARNING",
            "code": "chest.panel",
            "summary": "Painel operacional publicado."
            if panel_ok
            else "Painel operacional ausente ou inconsistente.",
            "detail": "; ".join(panel_errors[:3]),
            "action": "Execute a recuperacao do painel." if not panel_ok else "",
            "checked_at": now,
        }
    )
    return checks


async def admin_summary(
    session: AsyncSession, *, guild_id: str, actor: ActorContextIn
) -> dict[str, Any]:
    await _require(session, guild_id=guild_id, capability="chest.audit", actor=actor)
    draft = await catalog_draft(session, guild_id=guild_id)
    instance = await ensure_module_instance(
        session, guild_id=guild_id, module_key=MODULE_KEY
    )
    movements = int(
        await session.scalar(
            select(func.count())
            .select_from(ChestMovement)
            .where(ChestMovement.guild_id == guild_id)
        )
        or 0
    )
    recent = list(
        (
            await session.execute(
                select(ChestMovement)
                .where(ChestMovement.guild_id == guild_id)
                .order_by(ChestMovement.created_at.desc())
                .limit(5)
            )
        ).scalars()
    )
    balances = list(
        (
            await session.execute(
                select(ChestBalance)
                .where(ChestBalance.guild_id == guild_id)
                .order_by(ChestBalance.chest_id, ChestBalance.item_id)
                .limit(50)
            )
        ).scalars()
    )
    checks = await diagnostics(session, guild_id=guild_id)
    panels = list(
        (
            await session.execute(
                select(PanelInstance).where(
                    PanelInstance.guild_id == guild_id,
                    PanelInstance.module_key == MODULE_KEY,
                    PanelInstance.panel_key == "chest",
                )
            )
        ).scalars()
    )
    return {
        "lifecycle": instance.lifecycle.value,
        "published": instance.published_config_version_id is not None,
        "version": draft["base_published_version"],
        "revision": draft["revision"],
        "chests": len(draft["chests"]),
        "items": len(draft["items"]),
        "movements": movements,
        "recent": [movement_out(row) for row in recent],
        "stock": [
            {
                "chest_id": row.chest_id,
                "item_id": row.item_id,
                "quantity": str(row.quantity),
                "sequence": row.sequence,
            }
            for row in balances
        ],
        "panels": [
            {
                "chest_id": panel.resource_id,
                "state": panel.state.value,
                "channel_id": panel.channel_id,
                "message_id": panel.message_id,
                "last_error": panel.last_error,
            }
            for panel in panels
        ],
        "health": "OK" if all(row["status"] == "OK" for row in checks) else "ATTENTION",
    }
