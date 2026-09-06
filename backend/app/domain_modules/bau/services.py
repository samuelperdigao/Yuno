from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain_modules.bau.domain import (
    DEFAULT_CATALOG,
    BauDomainError,
    apply_delta,
    normalize_name,
    parse_delta,
)
from app.domain_modules.bau.models import BauCategory, BauItem, BauMovement, BauStock
from app.domain_modules.bau.schemas import BauConfig
from app.platform.audit import write_audit
from app.platform.models import ModuleConfigVersion, ModuleInstance, ModuleLifecycle
from app.platform.outbox import enqueue_delivery

log = logging.getLogger("yuno.bau")


def _http(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


async def _published_configuration(
    session: AsyncSession, guild_id: str, *, require_active: bool = True
) -> tuple[ModuleInstance, ModuleConfigVersion, BauConfig]:
    query = (
        select(ModuleInstance, ModuleConfigVersion)
        .join(
            ModuleConfigVersion,
            ModuleConfigVersion.id == ModuleInstance.published_config_version_id,
        )
        .where(
            ModuleInstance.guild_id == guild_id,
            ModuleInstance.module_key == "bau",
            ModuleConfigVersion.guild_id == guild_id,
            ModuleConfigVersion.module_key == "bau",
        )
    )
    row = (await session.execute(query)).one_or_none()
    if row is None:
        raise _http(409, "bau.not_configured", "Baú ainda não foi publicado.")
    instance, version = row
    if require_active and instance.lifecycle != ModuleLifecycle.active:
        raise _http(409, "bau.not_active", "Baú não está ativo.")
    config = BauConfig.model_validate(version.data or {})
    if require_active and not config.enabled:
        raise _http(409, "bau.disabled", "Baú está desabilitado.")
    return instance, version, config


async def effective_configuration(
    session: AsyncSession, *, guild_id: str, require_active: bool = True
) -> tuple[ModuleConfigVersion, BauConfig]:
    _, version, config = await _published_configuration(
        session, guild_id, require_active=require_active
    )
    return version, config


async def seed_default_catalog_if_empty(
    session: AsyncSession, *, guild_id: str, actor_id: str, correlation_id: str
) -> int:
    """Popula o catálogo padrão na primeira publicação. Idempotente: nunca
    sobrescreve um catálogo já existente, mesmo que tenha sido esvaziado."""

    existing = await session.scalar(
        select(func.count(BauCategory.id)).where(BauCategory.guild_id == guild_id)
    )
    if existing:
        return 0
    created = 0
    for position, (category_name, item_names) in enumerate(DEFAULT_CATALOG):
        category = BauCategory(guild_id=guild_id, name=category_name, position=position)
        session.add(category)
        await session.flush()
        for item_position, item_name in enumerate(item_names):
            item = BauItem(
                guild_id=guild_id,
                category_id=category.id,
                name=item_name,
                position=item_position,
            )
            session.add(item)
            await session.flush()
            session.add(BauStock(item_id=item.id, guild_id=guild_id, quantity=0))
        created += 1
    await write_audit(
        session,
        guild_id=guild_id,
        module_key="bau",
        actor_type="system",
        actor_id=actor_id,
        action="bau.catalog_seeded",
        resource_type="bau_category",
        correlation_id=correlation_id,
        after={"categories": created},
    )
    await session.commit()
    return created


async def list_catalog(session: AsyncSession, *, guild_id: str) -> list[dict[str, Any]]:
    categories = list(
        (
            await session.execute(
                select(BauCategory)
                .where(BauCategory.guild_id == guild_id)
                .order_by(BauCategory.position, BauCategory.name)
            )
        ).scalars()
    )
    rows = (
        await session.execute(
            select(BauItem, BauStock)
            .outerjoin(BauStock, BauStock.item_id == BauItem.id)
            .where(BauItem.guild_id == guild_id)
            .order_by(BauItem.position, BauItem.name)
        )
    ).all()
    items_by_category: dict[str, list[dict[str, Any]]] = {}
    for item, stock in rows:
        items_by_category.setdefault(item.category_id, []).append(
            {
                "id": item.id,
                "name": item.name,
                "position": item.position,
                "quantity": stock.quantity if stock is not None else 0,
                "generation": stock.generation if stock is not None else 0,
            }
        )
    return [
        {
            "id": category.id,
            "name": category.name,
            "position": category.position,
            "items": items_by_category.get(category.id, []),
        }
        for category in categories
    ]


async def stock_summary(session: AsyncSession, *, guild_id: str) -> list[dict[str, Any]]:
    catalog = await list_catalog(session, guild_id=guild_id)
    return [
        {
            "id": category["id"],
            "name": category["name"],
            "item_count": len(category["items"]),
            "total_quantity": sum(item["quantity"] for item in category["items"]),
        }
        for category in catalog
    ]


async def _get_category_by_name(session: AsyncSession, guild_id: str, name: str) -> BauCategory:
    category = (
        await session.execute(
            select(BauCategory).where(BauCategory.guild_id == guild_id, BauCategory.name == name)
        )
    ).scalar_one_or_none()
    if category is None:
        raise _http(404, "bau.category_not_found", f"Categoria '{name}' não encontrada.")
    return category


async def _get_item_by_name(session: AsyncSession, guild_id: str, name: str) -> BauItem:
    item = (
        await session.execute(select(BauItem).where(BauItem.guild_id == guild_id, BauItem.name == name))
    ).scalar_one_or_none()
    if item is None:
        raise _http(404, "bau.item_not_found", f"Item '{name}' não encontrado.")
    return item


async def add_category(
    session: AsyncSession, *, guild_id: str, actor_id: str, correlation_id: str, name: str
) -> BauCategory:
    try:
        clean_name = normalize_name(name, max_length=60, label="Nome da categoria")
    except BauDomainError as exc:
        raise _http(422, "bau.invalid_input", str(exc)) from exc
    existing = (
        await session.execute(
            select(BauCategory).where(BauCategory.guild_id == guild_id, BauCategory.name == clean_name)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise _http(409, "bau.category_exists", f"Categoria '{clean_name}' já existe.")
    position = await session.scalar(
        select(func.coalesce(func.max(BauCategory.position), -1)).where(BauCategory.guild_id == guild_id)
    )
    category = BauCategory(guild_id=guild_id, name=clean_name, position=(position or -1) + 1)
    session.add(category)
    await session.flush()
    await write_audit(
        session,
        guild_id=guild_id,
        module_key="bau",
        actor_id=actor_id,
        action="bau.category_created",
        resource_type="bau_category",
        resource_id=category.id,
        correlation_id=correlation_id,
        after={"name": clean_name},
    )
    await session.commit()
    return category


async def rename_category(
    session: AsyncSession,
    *,
    guild_id: str,
    actor_id: str,
    correlation_id: str,
    name: str,
    new_name: str,
) -> BauCategory:
    category = await _get_category_by_name(session, guild_id, name)
    try:
        clean_name = normalize_name(new_name, max_length=60, label="Nome da categoria")
    except BauDomainError as exc:
        raise _http(422, "bau.invalid_input", str(exc)) from exc
    conflict = (
        await session.execute(
            select(BauCategory).where(BauCategory.guild_id == guild_id, BauCategory.name == clean_name)
        )
    ).scalar_one_or_none()
    if conflict is not None and conflict.id != category.id:
        raise _http(409, "bau.category_exists", f"Categoria '{clean_name}' já existe.")
    before = category.name
    category.name = clean_name
    await session.flush()
    await write_audit(
        session,
        guild_id=guild_id,
        module_key="bau",
        actor_id=actor_id,
        action="bau.category_renamed",
        resource_type="bau_category",
        resource_id=category.id,
        correlation_id=correlation_id,
        before={"name": before},
        after={"name": clean_name},
    )
    await session.commit()
    return category


async def remove_category(
    session: AsyncSession, *, guild_id: str, actor_id: str, correlation_id: str, name: str
) -> None:
    category = await _get_category_by_name(session, guild_id, name)
    item_count = await session.scalar(
        select(func.count(BauItem.id)).where(BauItem.category_id == category.id)
    )
    await session.delete(category)
    await write_audit(
        session,
        guild_id=guild_id,
        module_key="bau",
        actor_id=actor_id,
        action="bau.category_removed",
        resource_type="bau_category",
        resource_id=category.id,
        correlation_id=correlation_id,
        before={"name": category.name, "item_count": int(item_count or 0)},
    )
    await session.commit()


async def add_item(
    session: AsyncSession,
    *,
    guild_id: str,
    actor_id: str,
    correlation_id: str,
    category_name: str,
    name: str,
) -> BauItem:
    category = await _get_category_by_name(session, guild_id, category_name)
    try:
        clean_name = normalize_name(name, max_length=80, label="Nome do item")
    except BauDomainError as exc:
        raise _http(422, "bau.invalid_input", str(exc)) from exc
    existing = (
        await session.execute(
            select(BauItem).where(BauItem.guild_id == guild_id, BauItem.name == clean_name)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise _http(409, "bau.item_exists", f"Item '{clean_name}' já existe.")
    position = await session.scalar(
        select(func.coalesce(func.max(BauItem.position), -1)).where(BauItem.category_id == category.id)
    )
    item = BauItem(
        guild_id=guild_id, category_id=category.id, name=clean_name, position=(position or -1) + 1
    )
    session.add(item)
    await session.flush()
    session.add(BauStock(item_id=item.id, guild_id=guild_id, quantity=0))
    await write_audit(
        session,
        guild_id=guild_id,
        module_key="bau",
        actor_id=actor_id,
        action="bau.item_created",
        resource_type="bau_item",
        resource_id=item.id,
        correlation_id=correlation_id,
        after={"name": clean_name, "category": category.name},
    )
    await session.commit()
    return item


async def rename_item(
    session: AsyncSession,
    *,
    guild_id: str,
    actor_id: str,
    correlation_id: str,
    name: str,
    new_name: str,
) -> BauItem:
    item = await _get_item_by_name(session, guild_id, name)
    try:
        clean_name = normalize_name(new_name, max_length=80, label="Nome do item")
    except BauDomainError as exc:
        raise _http(422, "bau.invalid_input", str(exc)) from exc
    conflict = (
        await session.execute(
            select(BauItem).where(BauItem.guild_id == guild_id, BauItem.name == clean_name)
        )
    ).scalar_one_or_none()
    if conflict is not None and conflict.id != item.id:
        raise _http(409, "bau.item_exists", f"Item '{clean_name}' já existe.")
    before = item.name
    item.name = clean_name
    await session.flush()
    await write_audit(
        session,
        guild_id=guild_id,
        module_key="bau",
        actor_id=actor_id,
        action="bau.item_renamed",
        resource_type="bau_item",
        resource_id=item.id,
        correlation_id=correlation_id,
        before={"name": before},
        after={"name": clean_name},
    )
    await session.commit()
    return item


async def remove_item(
    session: AsyncSession, *, guild_id: str, actor_id: str, correlation_id: str, name: str
) -> None:
    item = await _get_item_by_name(session, guild_id, name)
    await session.delete(item)
    await write_audit(
        session,
        guild_id=guild_id,
        module_key="bau",
        actor_id=actor_id,
        action="bau.item_removed",
        resource_type="bau_item",
        resource_id=item.id,
        correlation_id=correlation_id,
        before={"name": item.name},
    )
    await session.commit()


async def apply_movements(
    session: AsyncSession,
    *,
    guild_id: str,
    actor_id: str,
    correlation_id: str,
    items: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    """Aplica um lote de deltas de estoque numa única transação.

    As linhas de `bau_stock` são travadas em ordem estável de `item_id` para
    que duas movimentações concorrentes na mesma guild nunca causem deadlock;
    `generation` sobe a cada escrita bem-sucedida como contador otimista.
    """

    _, version, config = await _published_configuration(session, guild_id)
    ordered = sorted(items, key=lambda pair: pair[0])
    changes: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for item_id, raw in ordered:
        try:
            delta = parse_delta(raw)
        except BauDomainError as exc:
            raise _http(422, "bau.invalid_input", str(exc)) from exc
        if delta is None:
            continue
        item = (
            await session.execute(
                select(BauItem).where(BauItem.id == item_id, BauItem.guild_id == guild_id)
            )
        ).scalar_one_or_none()
        if item is None:
            raise _http(404, "bau.item_not_found", f"Item {item_id} não encontrado.")
        stock = (
            await session.execute(
                select(BauStock)
                .where(BauStock.item_id == item_id, BauStock.guild_id == guild_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if stock is None:
            raise _http(404, "bau.item_not_found", f"Item '{item.name}' sem estoque inicializado.")
        try:
            after = apply_delta(stock.quantity, delta, item_name=item.name)
        except BauDomainError as exc:
            raise _http(422, "bau.invalid_operation", str(exc)) from exc
        before = stock.quantity
        stock.quantity = after
        stock.generation += 1
        stock.updated_by = actor_id
        movement = BauMovement(
            guild_id=guild_id,
            item_id=item.id,
            item_name=item.name,
            actor_id=actor_id,
            operation="entrada" if delta > 0 else "saida",
            quantity_delta=delta,
            quantity_before=before,
            quantity_after=after,
            generation_after=stock.generation,
            correlation_id=correlation_id,
        )
        session.add(movement)
        changes.append(
            {
                "item_id": item.id,
                "item_name": item.name,
                "delta": delta,
                "before": before,
                "after": after,
            }
        )
    if not changes:
        raise _http(422, "bau.no_changes", "Nenhuma alteração informada.")
    await session.flush()
    await write_audit(
        session,
        guild_id=guild_id,
        module_key="bau",
        actor_id=actor_id,
        action="bau.stock_moved",
        resource_type="bau_stock",
        correlation_id=correlation_id,
        after={"changes": changes},
        config_version=version.version,
    )
    if config.log_channel_id:
        await enqueue_delivery(
            session,
            guild_id=guild_id,
            module_key="bau",
            renderer_key="bau.log",
            destination_type="channel",
            destination_id=config.log_channel_id,
            resource_type="bau_stock",
            resource_id="",
            payload={
                "operation": "movimentacao",
                "actor_id": actor_id,
                "changes": changes,
                "log_title": config.log_title,
            },
            priority=100,
            available_at=now,
            idempotency_key=f"{correlation_id}:bau.log",
            correlation_id=correlation_id,
            max_attempts=10,
        )
    await session.commit()
    return changes


async def clear_stock(
    session: AsyncSession, *, guild_id: str, actor_id: str, correlation_id: str
) -> int:
    _, version, config = await _published_configuration(session, guild_id, require_active=False)
    rows = list(
        (
            await session.execute(
                select(BauStock)
                .where(BauStock.guild_id == guild_id, BauStock.quantity > 0)
                .with_for_update()
            )
        ).scalars()
    )
    if not rows:
        return 0
    item_names = {
        item.id: item.name
        for item in (
            await session.execute(select(BauItem).where(BauItem.guild_id == guild_id))
        ).scalars()
    }
    now = datetime.now(timezone.utc)
    for stock in rows:
        before = stock.quantity
        stock.quantity = 0
        stock.generation += 1
        stock.updated_by = actor_id
        session.add(
            BauMovement(
                guild_id=guild_id,
                item_id=stock.item_id,
                item_name=item_names.get(stock.item_id, "?"),
                actor_id=actor_id,
                operation="limpeza",
                quantity_delta=-before,
                quantity_before=before,
                quantity_after=0,
                generation_after=stock.generation,
                correlation_id=correlation_id,
            )
        )
    await session.flush()
    await write_audit(
        session,
        guild_id=guild_id,
        module_key="bau",
        actor_id=actor_id,
        action="bau.stock_cleared",
        resource_type="bau_stock",
        correlation_id=correlation_id,
        after={"items_reset": len(rows)},
        config_version=version.version,
    )
    if config.log_channel_id:
        await enqueue_delivery(
            session,
            guild_id=guild_id,
            module_key="bau",
            renderer_key="bau.log",
            destination_type="channel",
            destination_id=config.log_channel_id,
            resource_type="bau_stock",
            resource_id="",
            payload={
                "operation": "limpeza",
                "actor_id": actor_id,
                "items_reset": len(rows),
                "log_title": config.log_title,
            },
            priority=100,
            available_at=now,
            idempotency_key=f"{correlation_id}:bau.clear",
            correlation_id=correlation_id,
            max_attempts=10,
        )
    await session.commit()
    return len(rows)
