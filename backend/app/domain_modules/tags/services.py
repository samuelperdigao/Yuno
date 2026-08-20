from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.domain_modules.registration.domain import OrganizationMemberStatus
from app.domain_modules.registration.identity import read_base_member_identity
from app.domain_modules.registration.models import OrganizationMember
from app.domain_modules.tags.domain import (
    MemberDiscordSnapshot,
    TagBinding,
    TagResolution,
    TagResolutionStatus,
    TagSyncRunMode,
    TagSyncRunStatus,
    TagSyncState,
    normalize_snowflake,
    normalize_tag,
    resolve_tag,
)
from app.domain_modules.tags.models import (
    TagRoleBindingDraft,
    TagRoleBindingVersion,
    TagSyncIntent,
    TagSyncRun,
    TagSyncRunItem,
)
from app.platform.audit import write_audit
from app.platform.automation import schedule_task
from app.platform.configuration import get_or_create_draft
from app.platform.lifecycle import ensure_module_instance, get_module_instance
from app.platform.models import ModuleConfigDraft, ModuleInstance, ModuleLifecycle


ACTIVE_RUN_STATES = (
    TagSyncRunStatus.pending,
    TagSyncRunStatus.planning,
    TagSyncRunStatus.running,
)
TERMINAL_ITEM_STATES = (
    TagSyncState.applied,
    TagSyncState.skipped,
    TagSyncState.blocked,
    TagSyncState.failed,
    TagSyncState.cancelled,
)


def _conflict(detail: str, **current: int) -> HTTPException:
    return HTTPException(status_code=409, detail={"detail": detail, **current})


def _hash_nickname(value: str | None) -> str | None:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value is not None else None


def binding_dict(item: TagRoleBindingDraft | TagRoleBindingVersion) -> dict:
    return {
        "id": item.id,
        "guild_id": item.guild_id,
        "discord_role_id": item.discord_role_id,
        "tag": item.tag,
        "enabled": item.enabled,
    }


def intent_dict(item: TagSyncIntent) -> dict:
    return {
        "id": item.id,
        "guild_id": item.guild_id,
        "discord_user_id": item.discord_user_id,
        "desired_revision": item.desired_revision,
        "applied_revision": item.applied_revision,
        "state": item.state,
        "winning_role_id": item.winning_role_id,
        "last_result": item.last_result,
        "last_error_code": item.last_error_code,
        "attempts": item.attempts,
        "updated_at": item.updated_at,
    }


def run_dict(item: TagSyncRun) -> dict:
    return {
        "id": item.id,
        "guild_id": item.guild_id,
        "mode": item.mode,
        "reason": item.reason,
        "config_version_id": item.config_version_id,
        "status": item.status,
        "cursor_user_id": item.cursor_user_id,
        "total_items": item.total_items,
        "planned_items": item.planned_items,
        "succeeded_items": item.succeeded_items,
        "skipped_items": item.skipped_items,
        "blocked_items": item.blocked_items,
        "failed_items": item.failed_items,
        "cancel_requested_at": item.cancel_requested_at,
        "created_at": item.created_at,
        "started_at": item.started_at,
        "finished_at": item.finished_at,
    }


async def _tags_instance(
    session: AsyncSession, *, guild_id: str, create: bool = False, for_update: bool = False
) -> ModuleInstance | None:
    if create:
        return await ensure_module_instance(
            session, guild_id=guild_id, module_key="tags", for_update=for_update
        )
    return await get_module_instance(
        session, guild_id=guild_id, module_key="tags", for_update=for_update
    )


async def _checked_draft(
    session: AsyncSession,
    *,
    guild_id: str,
    expected_revision: int,
    expected_published_version: int,
) -> tuple[ModuleInstance, ModuleConfigDraft]:
    instance = await _tags_instance(session, guild_id=guild_id, create=True, for_update=True)
    assert instance is not None
    draft = await get_or_create_draft(
        session, guild_id=guild_id, module_key="tags", for_update=True
    )
    if draft.revision != expected_revision:
        raise _conflict("Rascunho alterado por outra sessao.", current_revision=draft.revision)
    if draft.base_published_version != expected_published_version:
        raise _conflict(
            "A configuracao publicada mudou desde a abertura do rascunho.",
            current_published_version=draft.base_published_version,
        )
    return instance, draft


async def list_draft_bindings(session: AsyncSession, *, guild_id: str) -> tuple[ModuleConfigDraft, list[TagRoleBindingDraft]]:
    draft = await get_or_create_draft(session, guild_id=guild_id, module_key="tags")
    items = list(
        (
            await session.execute(
                select(TagRoleBindingDraft)
                .where(
                    TagRoleBindingDraft.guild_id == guild_id,
                    TagRoleBindingDraft.module_instance_id == draft.module_instance_id,
                )
                .order_by(TagRoleBindingDraft.created_at, TagRoleBindingDraft.id)
            )
        ).scalars()
    )
    return draft, items


async def effective_bindings(session: AsyncSession, *, guild_id: str) -> tuple[ModuleInstance | None, list[TagRoleBindingVersion]]:
    instance = await _tags_instance(session, guild_id=guild_id)
    if instance is None or instance.published_config_version_id is None:
        return instance, []
    items = list(
        (
            await session.execute(
                select(TagRoleBindingVersion)
                .where(
                    TagRoleBindingVersion.guild_id == guild_id,
                    TagRoleBindingVersion.module_instance_id == instance.id,
                    TagRoleBindingVersion.config_version_id == instance.published_config_version_id,
                )
                .order_by(TagRoleBindingVersion.id)
            )
        ).scalars()
    )
    return instance, items


async def upsert_draft_binding(
    session: AsyncSession,
    *,
    guild_id: str,
    discord_role_id: str,
    tag: str,
    enabled: bool,
    actor_id: str,
    expected_revision: int,
    expected_published_version: int,
    correlation_id: str,
) -> tuple[ModuleConfigDraft, TagRoleBindingDraft]:
    role_id = normalize_snowflake(discord_role_id, field="Cargo")
    if role_id == guild_id:
        raise HTTPException(status_code=422, detail="O cargo @everyone nao pode receber Tag.")
    normalized_tag = normalize_tag(tag)
    instance, draft = await _checked_draft(
        session,
        guild_id=guild_id,
        expected_revision=expected_revision,
        expected_published_version=expected_published_version,
    )
    item = (
        await session.execute(
            select(TagRoleBindingDraft)
            .where(
                TagRoleBindingDraft.guild_id == guild_id,
                TagRoleBindingDraft.module_instance_id == instance.id,
                TagRoleBindingDraft.discord_role_id == role_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    before = binding_dict(item) if item is not None else {}
    if item is None:
        item = TagRoleBindingDraft(
            module_instance_id=instance.id,
            guild_id=guild_id,
            discord_role_id=role_id,
            tag=normalized_tag,
            enabled=enabled,
            created_by=actor_id,
            updated_by=actor_id,
        )
        session.add(item)
        action = "tags.binding_draft_created"
    else:
        previous_tag = item.tag
        previous_enabled = item.enabled
        item.tag = normalized_tag
        item.enabled = enabled
        item.updated_by = actor_id
        if previous_tag == normalized_tag and previous_enabled != enabled:
            action = (
                "tags.binding_draft_enabled" if enabled else "tags.binding_draft_disabled"
            )
        else:
            action = "tags.binding_draft_updated"
    draft.revision += 1
    draft.updated_by = actor_id
    await session.flush()
    await write_audit(
        session,
        guild_id=guild_id,
        module_key="tags",
        action=action,
        resource_type="tag_role_binding_draft",
        resource_id=item.id,
        actor_id=actor_id,
        before={key: before.get(key) for key in ("discord_role_id", "tag", "enabled") if key in before},
        after={"discord_role_id": role_id, "tag": normalized_tag, "enabled": enabled, "revision": draft.revision},
        correlation_id=correlation_id,
    )
    await session.commit()
    await session.refresh(draft)
    await session.refresh(item)
    return draft, item


async def delete_draft_binding(
    session: AsyncSession,
    *,
    guild_id: str,
    discord_role_id: str,
    actor_id: str,
    expected_revision: int,
    expected_published_version: int,
    correlation_id: str,
) -> ModuleConfigDraft:
    role_id = normalize_snowflake(discord_role_id, field="Cargo")
    instance, draft = await _checked_draft(
        session,
        guild_id=guild_id,
        expected_revision=expected_revision,
        expected_published_version=expected_published_version,
    )
    item = (
        await session.execute(
            select(TagRoleBindingDraft)
            .where(
                TagRoleBindingDraft.guild_id == guild_id,
                TagRoleBindingDraft.module_instance_id == instance.id,
                TagRoleBindingDraft.discord_role_id == role_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Vinculo nao encontrado neste rascunho.")
    before = {"discord_role_id": item.discord_role_id, "tag": item.tag, "enabled": item.enabled}
    resource_id = item.id
    await session.delete(item)
    draft.revision += 1
    draft.updated_by = actor_id
    await write_audit(
        session,
        guild_id=guild_id,
        module_key="tags",
        action="tags.binding_draft_deleted",
        resource_type="tag_role_binding_draft",
        resource_id=resource_id,
        actor_id=actor_id,
        before=before,
        after={"revision": draft.revision},
        correlation_id=correlation_id,
    )
    await session.commit()
    await session.refresh(draft)
    return draft


async def preview(
    session: AsyncSession,
    *,
    guild_id: str,
    discord_user_id: str,
    snapshot: MemberDiscordSnapshot,
    source: str,
    base_only: bool,
) -> tuple[TagResolution, dict]:
    if snapshot.guild_id != guild_id or snapshot.discord_user_id != discord_user_id:
        raise HTTPException(status_code=403, detail="Snapshot pertence a outro membro ou guild.")
    identity = await read_base_member_identity(
        session, guild_id=guild_id, discord_user_id=discord_user_id
    )
    if identity is None:
        return TagResolution(TagResolutionStatus.blocked, None, blocker="identity_missing"), {}
    if identity.status != OrganizationMemberStatus.active:
        return TagResolution(TagResolutionStatus.blocked, None, blocker="identity_inactive"), {
            "identity_fingerprint": identity.fingerprint
        }
    if source == "draft":
        draft, rows = await list_draft_bindings(session, guild_id=guild_id)
        binding_source = [TagBinding(item.discord_role_id, item.tag, item.enabled) for item in rows]
        metadata = {"source": "draft", "revision": draft.revision}
    else:
        instance, rows = await effective_bindings(session, guild_id=guild_id)
        binding_source = [TagBinding(item.discord_role_id, item.tag, item.enabled) for item in rows]
        metadata = {
            "source": "effective",
            "config_version_id": instance.published_config_version_id if instance else None,
        }
    return (
        resolve_tag(
            base_nickname=identity.base_nickname,
            snapshot=snapshot,
            bindings=binding_source,
            base_only=base_only,
        ),
        {**metadata, "identity_fingerprint": identity.fingerprint},
    )


async def _locked_intent(
    session: AsyncSession, *, guild_id: str, discord_user_id: str
) -> TagSyncIntent | None:
    return (
        await session.execute(
            select(TagSyncIntent)
            .where(
                TagSyncIntent.guild_id == guild_id,
                TagSyncIntent.discord_user_id == discord_user_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()


async def request_member_sync(
    session: AsyncSession,
    *,
    guild_id: str,
    discord_user_id: str,
    observed_fingerprint: str | None,
    reason: str,
    correlation_id: str,
    run_id: str | None = None,
    commit: bool = True,
) -> TagSyncIntent | None:
    user_id = normalize_snowflake(discord_user_id, field="Usuario")
    instance = await _tags_instance(session, guild_id=guild_id)
    if (
        instance is None
        or instance.lifecycle != ModuleLifecycle.active
        or instance.published_config_version_id is None
    ):
        return None
    intent = await _locked_intent(session, guild_id=guild_id, discord_user_id=user_id)
    if intent is None:
        intent = TagSyncIntent(guild_id=guild_id, discord_user_id=user_id)
        try:
            async with session.begin_nested():
                session.add(intent)
                await session.flush()
        except IntegrityError:
            intent = await _locked_intent(
                session, guild_id=guild_id, discord_user_id=user_id
            )
            assert intent is not None
    intent.desired_revision += 1
    revision = intent.desired_revision
    intent.observed_fingerprint = observed_fingerprint
    lease_until = intent.lease_until
    if lease_until is not None and lease_until.tzinfo is None:
        lease_until = lease_until.replace(tzinfo=timezone.utc)
    processing_active = bool(
        intent.processing_token
        and lease_until is not None
        and lease_until > datetime.now(timezone.utc)
    )
    if not processing_active:
        intent.state = TagSyncState.pending
    intent.correlation_id = correlation_id
    intent.last_error_code = None
    intent.last_error_detail = None
    await session.flush()
    run_item: TagSyncRunItem | None = None
    if run_id is not None:
        run_item = TagSyncRunItem(
            run_id=run_id,
            guild_id=guild_id,
            discord_user_id=user_id,
            intent_revision=revision,
        )
        session.add(run_item)
        await session.flush()
    await schedule_task(
        session,
        guild_id=guild_id,
        module_key="tags",
        job_key="tags.member.sync",
        resource_type="tag_sync_intent",
        resource_id=intent.id,
        payload={
            "intent_id": intent.id,
            "revision": revision,
            "discord_user_id": user_id,
            "run_item_id": run_item.id if run_item else None,
            "reason": reason,
        },
        due_at=datetime.now(timezone.utc),
        idempotency_key=f"intent:{intent.id}:r{revision}",
        correlation_id=correlation_id,
        max_attempts=None,
        commit=False,
    )
    if commit:
        await session.commit()
        await session.refresh(intent)
    return intent


async def create_sync_run(
    session: AsyncSession,
    *,
    guild_id: str,
    mode: TagSyncRunMode,
    reason: str,
    actor_id: str | None,
    correlation_id: str,
    due_at: datetime | None = None,
    supersede_active: bool = False,
) -> TagSyncRun:
    instance = await _tags_instance(session, guild_id=guild_id, for_update=True)
    if (
        instance is None
        or instance.lifecycle != ModuleLifecycle.active
        or instance.published_config_version_id is None
    ):
        raise HTTPException(status_code=409, detail="Sistema de Tags precisa estar ativo e publicado.")
    active = (
        await session.execute(
            select(TagSyncRun)
            .where(TagSyncRun.guild_id == guild_id, TagSyncRun.status.in_(ACTIVE_RUN_STATES))
            .order_by(TagSyncRun.created_at)
            .with_for_update()
        )
    ).scalars().first()
    if active is not None:
        if active.mode != mode:
            if not supersede_active:
                raise HTTPException(
                    status_code=409,
                    detail="Ja existe um run ativo com outro modo; conclua ou cancele antes.",
                )
            now = datetime.now(timezone.utc)
            active.cancel_requested_at = now
            active.status = TagSyncRunStatus.cancelled
            active.finished_at = now
            await session.execute(
                update(TagSyncRunItem)
                .where(
                    TagSyncRunItem.run_id == active.id,
                    TagSyncRunItem.guild_id == guild_id,
                    TagSyncRunItem.state == TagSyncState.pending,
                )
                .values(
                    state=TagSyncState.cancelled,
                    result_code="superseded_by_request",
                )
            )
            await session.flush()
        else:
            return active
    run = TagSyncRun(
        guild_id=guild_id,
        mode=mode,
        reason=reason,
        config_version_id=instance.published_config_version_id,
        requested_by=actor_id,
        correlation_id=correlation_id,
    )
    try:
        async with session.begin_nested():
            session.add(run)
            await session.flush()
    except IntegrityError:
        active = (
            await session.execute(
                select(TagSyncRun)
                .where(TagSyncRun.guild_id == guild_id, TagSyncRun.status.in_(ACTIVE_RUN_STATES))
                .order_by(TagSyncRun.created_at)
                .with_for_update()
            )
        ).scalars().first()
        if active is None:
            raise
        if active.mode != mode:
            raise HTTPException(
                status_code=409,
                detail="Ja existe um run ativo com outro modo; conclua ou cancele antes.",
            )
        return active
    await schedule_task(
        session,
        guild_id=guild_id,
        module_key="tags",
        job_key="tags.run.plan",
        resource_type="tag_sync_run",
        resource_id=run.id,
        payload={"run_id": run.id},
        due_at=due_at or datetime.now(timezone.utc),
        idempotency_key=f"run:{run.id}:plan:start",
        correlation_id=correlation_id,
        max_attempts=None,
        commit=False,
    )
    await write_audit(
        session,
        guild_id=guild_id,
        module_key="tags",
        action="tags.cleanup_requested" if mode == TagSyncRunMode.base_only else "tags.sync_requested",
        resource_type="tag_sync_run",
        resource_id=run.id,
        actor_type="user" if actor_id else "system",
        actor_id=actor_id,
        after={"mode": mode.value, "reason": reason, "config_version_id": run.config_version_id},
        correlation_id=correlation_id,
    )
    await session.commit()
    await session.refresh(run)
    return run


async def get_sync_run(session: AsyncSession, *, guild_id: str, run_id: str) -> TagSyncRun:
    run = (
        await session.execute(
            select(TagSyncRun).where(TagSyncRun.id == run_id, TagSyncRun.guild_id == guild_id)
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run de Tags nao encontrado nesta guild.")
    return run


async def cancel_sync_run(
    session: AsyncSession,
    *,
    guild_id: str,
    run_id: str,
    actor_id: str,
    correlation_id: str,
) -> TagSyncRun:
    run = (
        await session.execute(
            select(TagSyncRun)
            .where(TagSyncRun.id == run_id, TagSyncRun.guild_id == guild_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run de Tags nao encontrado nesta guild.")
    if run.status not in ACTIVE_RUN_STATES:
        return run
    run.cancel_requested_at = datetime.now(timezone.utc)
    await session.execute(
        update(TagSyncRunItem)
        .where(
            TagSyncRunItem.run_id == run.id,
            TagSyncRunItem.guild_id == guild_id,
            TagSyncRunItem.state == TagSyncState.pending,
        )
        .values(state=TagSyncState.cancelled, result_code="cancelled")
    )
    await write_audit(
        session,
        guild_id=guild_id,
        module_key="tags",
        action="tags.sync_cancel_requested",
        resource_type="tag_sync_run",
        resource_id=run.id,
        actor_id=actor_id,
        correlation_id=correlation_id,
        after={"status": run.status.value},
    )
    await session.commit()
    await session.refresh(run)
    return run


async def _refresh_run_counts(session: AsyncSession, run: TagSyncRun) -> None:
    counts = dict(
        (
            await session.execute(
                select(TagSyncRunItem.state, func.count(TagSyncRunItem.id))
                .where(TagSyncRunItem.run_id == run.id, TagSyncRunItem.guild_id == run.guild_id)
                .group_by(TagSyncRunItem.state)
            )
        ).all()
    )
    run.succeeded_items = int(counts.get(TagSyncState.applied, 0))
    run.skipped_items = int(counts.get(TagSyncState.skipped, 0))
    run.blocked_items = int(counts.get(TagSyncState.blocked, 0))
    run.failed_items = int(counts.get(TagSyncState.failed, 0))


async def plan_sync_run_batch(session: AsyncSession, *, guild_id: str, run_id: str) -> TagSyncRun:
    run = (
        await session.execute(
            select(TagSyncRun)
            .where(TagSyncRun.id == run_id, TagSyncRun.guild_id == guild_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run de Tags nao encontrado nesta guild.")
    if run.status not in ACTIVE_RUN_STATES:
        return run
    if run.cancel_requested_at is not None:
        await session.execute(
            update(TagSyncRunItem)
            .where(
                TagSyncRunItem.run_id == run.id,
                TagSyncRunItem.guild_id == guild_id,
                TagSyncRunItem.state == TagSyncState.pending,
            )
            .values(state=TagSyncState.cancelled, result_code="cancelled")
        )
        run.status = TagSyncRunStatus.cancelled
        run.finished_at = datetime.now(timezone.utc)
        await _refresh_run_counts(session, run)
        await session.commit()
        return run
    if run.started_at is None:
        run.started_at = datetime.now(timezone.utc)
        run.total_items = int(
            await session.scalar(
                select(func.count(OrganizationMember.id)).where(
                    OrganizationMember.guild_id == guild_id,
                    OrganizationMember.status == OrganizationMemberStatus.active,
                )
            )
            or 0
        )
    run.status = TagSyncRunStatus.planning
    query = (
        select(OrganizationMember.discord_user_id)
        .where(
            OrganizationMember.guild_id == guild_id,
            OrganizationMember.status == OrganizationMemberStatus.active,
        )
        .order_by(OrganizationMember.discord_user_id)
        .limit(101)
    )
    if run.cursor_user_id is not None:
        query = query.where(OrganizationMember.discord_user_id > run.cursor_user_id)
    user_ids = list((await session.execute(query)).scalars())
    page, has_more = user_ids[:100], len(user_ids) > 100
    for user_id in page:
        await request_member_sync(
            session,
            guild_id=guild_id,
            discord_user_id=user_id,
            observed_fingerprint=None,
            reason=run.reason,
            correlation_id=run.correlation_id,
            run_id=run.id,
            commit=False,
        )
    run.planned_items += len(page)
    if page:
        run.cursor_user_id = page[-1]
    if has_more:
        await schedule_task(
            session,
            guild_id=guild_id,
            module_key="tags",
            job_key="tags.run.plan",
            resource_type="tag_sync_run",
            resource_id=run.id,
            payload={"run_id": run.id},
            due_at=datetime.now(timezone.utc),
            idempotency_key=f"run:{run.id}:plan:{run.cursor_user_id}",
            correlation_id=run.correlation_id,
            max_attempts=None,
            commit=False,
        )
    else:
        run.status = TagSyncRunStatus.running
        await schedule_task(
            session,
            guild_id=guild_id,
            module_key="tags",
            job_key="tags.run.finalize",
            resource_type="tag_sync_run",
            resource_id=run.id,
            payload={"run_id": run.id},
            due_at=datetime.now(timezone.utc) + timedelta(seconds=30),
            idempotency_key=f"run:{run.id}:finalize:0",
            correlation_id=run.correlation_id,
            max_attempts=None,
            commit=False,
        )
    await session.commit()
    await session.refresh(run)
    return run


async def finalize_sync_run(session: AsyncSession, *, guild_id: str, run_id: str) -> TagSyncRun:
    run = (
        await session.execute(
            select(TagSyncRun)
            .where(TagSyncRun.id == run_id, TagSyncRun.guild_id == guild_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run de Tags nao encontrado nesta guild.")
    if run.status not in ACTIVE_RUN_STATES:
        return run
    await _refresh_run_counts(session, run)
    terminal = int(
        await session.scalar(
            select(func.count(TagSyncRunItem.id)).where(
                TagSyncRunItem.run_id == run.id,
                TagSyncRunItem.guild_id == guild_id,
                TagSyncRunItem.state.in_(TERMINAL_ITEM_STATES),
            )
        )
        or 0
    )
    if run.cancel_requested_at is not None:
        run.status = TagSyncRunStatus.cancelled
        run.finished_at = datetime.now(timezone.utc)
    elif run.planned_items == run.total_items and terminal >= run.planned_items:
        run.status = (
            TagSyncRunStatus.completed_with_errors
            if run.failed_items or run.blocked_items
            else TagSyncRunStatus.completed
        )
        run.finished_at = datetime.now(timezone.utc)
    else:
        generation = int(datetime.now(timezone.utc).timestamp())
        await schedule_task(
            session,
            guild_id=guild_id,
            module_key="tags",
            job_key="tags.run.finalize",
            resource_type="tag_sync_run",
            resource_id=run.id,
            payload={"run_id": run.id},
            due_at=datetime.now(timezone.utc) + timedelta(seconds=30),
            idempotency_key=f"run:{run.id}:finalize:{generation}",
            correlation_id=run.correlation_id,
            max_attempts=None,
            commit=False,
        )
    if (
        run.mode == TagSyncRunMode.base_only
        and run.status in {TagSyncRunStatus.completed, TagSyncRunStatus.completed_with_errors}
    ):
        instance = await _tags_instance(session, guild_id=guild_id, for_update=True)
        if instance is not None and instance.lifecycle != ModuleLifecycle.inactive:
            before = instance.lifecycle.value
            instance.lifecycle = ModuleLifecycle.inactive
            for action in ("module.lifecycle_changed", "tags.lifecycle_changed"):
                await write_audit(
                    session,
                    guild_id=guild_id,
                    module_key="tags",
                    action=action,
                    resource_type="module_instance",
                    resource_id=str(instance.id),
                    actor_type="system",
                    before={"lifecycle": before},
                    after={"lifecycle": ModuleLifecycle.inactive.value, "reason": "cleanup_completed"},
                    correlation_id=run.correlation_id,
                )
    await session.commit()
    await session.refresh(run)
    return run


async def _owned_run_item(
    session: AsyncSession, *, guild_id: str, run_item_id: str | None, for_update: bool = False
) -> TagSyncRunItem | None:
    if run_item_id is None:
        return None
    query = select(TagSyncRunItem).where(
        TagSyncRunItem.id == run_item_id,
        TagSyncRunItem.guild_id == guild_id,
    )
    if for_update:
        query = query.with_for_update()
    item = (await session.execute(query)).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Item de run nao encontrado nesta guild.")
    return item


async def _terminal_prepare(
    session: AsyncSession,
    *,
    intent: TagSyncIntent,
    revision: int,
    run_item: TagSyncRunItem | None,
    state: TagSyncState,
    code: str,
    winning_role_id: str | None = None,
    expected_nickname: str | None = None,
) -> dict:
    intent.applied_revision = max(intent.applied_revision, revision)
    intent.state = state
    intent.last_result = code
    intent.last_error_code = code if state in {TagSyncState.blocked, TagSyncState.failed} else None
    intent.winning_role_id = winning_role_id
    intent.expected_nickname_hash = _hash_nickname(expected_nickname)
    if run_item is not None:
        run_item.state = state
        run_item.result_code = code
    await session.commit()
    return {"terminal": True, "state": state, "result_code": code}


async def _skip_obsolete_prepare(
    session: AsyncSession,
    *,
    run_item: TagSyncRunItem | None,
    code: str,
) -> dict:
    if run_item is not None:
        run_item.state = TagSyncState.skipped
        run_item.result_code = code
    await session.commit()
    return {"terminal": True, "state": TagSyncState.skipped, "result_code": code}


async def prepare_member_sync(
    session: AsyncSession,
    *,
    guild_id: str,
    intent_id: str,
    revision: int,
    run_item_id: str | None,
    snapshot: MemberDiscordSnapshot,
) -> dict:
    intent = (
        await session.execute(
            select(TagSyncIntent)
            .where(TagSyncIntent.id == intent_id, TagSyncIntent.guild_id == guild_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if intent is None:
        raise HTTPException(status_code=404, detail="Intent de Tags nao encontrado nesta guild.")
    if snapshot.guild_id != guild_id or snapshot.discord_user_id != intent.discord_user_id:
        raise HTTPException(status_code=403, detail="Snapshot pertence a outro membro ou guild.")
    run_item = await _owned_run_item(
        session, guild_id=guild_id, run_item_id=run_item_id, for_update=True
    )
    if revision < intent.desired_revision:
        return await _skip_obsolete_prepare(session, run_item=run_item, code="stale")
    if revision <= intent.applied_revision:
        return await _skip_obsolete_prepare(
            session, run_item=run_item, code="already_applied"
        )
    lease_until = intent.lease_until
    if lease_until is not None and lease_until.tzinfo is None:
        lease_until = lease_until.replace(tzinfo=timezone.utc)
    if (
        intent.processing_token
        and lease_until is not None
        and lease_until > datetime.now(timezone.utc)
    ):
        await session.commit()
        return {
            "terminal": False,
            "action": "retry_later",
            "retry_at": lease_until.isoformat(),
        }
    if intent.processing_token:
        intent.processing_token = None
        intent.lease_until = None
    base_only = False
    if run_item is not None:
        run = await get_sync_run(session, guild_id=guild_id, run_id=run_item.run_id)
        if run.cancel_requested_at is not None or run.status == TagSyncRunStatus.cancelled:
            return await _terminal_prepare(
                session, intent=intent, revision=revision, run_item=run_item,
                state=TagSyncState.cancelled, code="cancelled"
            )
        base_only = run.mode == TagSyncRunMode.base_only
    identity = await read_base_member_identity(
        session, guild_id=guild_id, discord_user_id=intent.discord_user_id
    )
    if identity is None:
        return await _terminal_prepare(
            session, intent=intent, revision=revision, run_item=run_item,
            state=TagSyncState.blocked, code="identity_missing"
        )
    if identity.status != OrganizationMemberStatus.active:
        return await _terminal_prepare(
            session, intent=intent, revision=revision, run_item=run_item,
            state=TagSyncState.blocked, code="identity_inactive"
        )
    _, rows = await effective_bindings(session, guild_id=guild_id)
    resolution = resolve_tag(
        base_nickname=identity.base_nickname,
        snapshot=snapshot,
        bindings=[TagBinding(item.discord_role_id, item.tag, item.enabled) for item in rows],
        base_only=base_only,
    )
    if resolution.status == TagResolutionStatus.already_correct:
        return await _terminal_prepare(
            session, intent=intent, revision=revision, run_item=run_item,
            state=TagSyncState.skipped, code="already_correct",
            winning_role_id=resolution.winning_role_id,
            expected_nickname=resolution.expected_nickname,
        )
    if resolution.status == TagResolutionStatus.blocked:
        return await _terminal_prepare(
            session, intent=intent, revision=revision, run_item=run_item,
            state=TagSyncState.blocked, code=resolution.blocker or "blocked",
            winning_role_id=resolution.winning_role_id,
            expected_nickname=resolution.expected_nickname,
        )
    token = uuid4().hex
    intent.state = TagSyncState.processing
    intent.processing_token = token
    intent.lease_until = datetime.now(timezone.utc) + timedelta(minutes=2)
    intent.last_attempt_at = datetime.now(timezone.utc)
    intent.attempts += 1
    intent.winning_role_id = resolution.winning_role_id
    intent.expected_nickname_hash = _hash_nickname(resolution.expected_nickname)
    if run_item is not None:
        run_item.state = TagSyncState.processing
    await session.commit()
    return {
        "terminal": False,
        "action": "edit_nickname",
        "processing_token": token,
        "expected_nickname": resolution.expected_nickname,
        "expected_nickname_hash": intent.expected_nickname_hash,
        "winning_role_id": resolution.winning_role_id,
    }


async def complete_member_sync(
    session: AsyncSession,
    *,
    guild_id: str,
    intent_id: str,
    revision: int,
    processing_token: str,
    run_item_id: str | None,
    result: str,
    result_code: str,
    applied_nickname_hash: str | None,
) -> TagSyncIntent:
    intent = (
        await session.execute(
            select(TagSyncIntent)
            .where(TagSyncIntent.id == intent_id, TagSyncIntent.guild_id == guild_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if intent is None:
        raise HTTPException(status_code=404, detail="Intent de Tags nao encontrado nesta guild.")
    if intent.processing_token != processing_token:
        raise HTTPException(status_code=409, detail="Token de processamento obsoleto.")
    run_item = await _owned_run_item(
        session, guild_id=guild_id, run_item_id=run_item_id, for_update=True
    )
    state = {
        "applied": TagSyncState.applied,
        "already_correct": TagSyncState.skipped,
        "blocked": TagSyncState.blocked,
        "skipped": TagSyncState.skipped,
    }[result]
    intent.applied_revision = max(intent.applied_revision, revision)
    intent.state = TagSyncState.pending if intent.desired_revision > revision else state
    intent.last_result = result_code
    intent.last_error_code = result_code if state == TagSyncState.blocked else None
    intent.applied_nickname_hash = applied_nickname_hash
    intent.processing_token = None
    intent.lease_until = None
    if run_item is not None:
        run_item.state = state
        run_item.result_code = result_code
    await session.commit()
    await session.refresh(intent)
    return intent


async def fail_member_sync(
    session: AsyncSession,
    *,
    guild_id: str,
    intent_id: str,
    revision: int,
    processing_token: str,
    run_item_id: str | None,
    error_code: str,
    error_detail: str,
    retryable: bool,
) -> TagSyncIntent:
    intent = (
        await session.execute(
            select(TagSyncIntent)
            .where(TagSyncIntent.id == intent_id, TagSyncIntent.guild_id == guild_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if intent is None:
        raise HTTPException(status_code=404, detail="Intent de Tags nao encontrado nesta guild.")
    if intent.processing_token != processing_token:
        raise HTTPException(status_code=409, detail="Token de processamento obsoleto.")
    run_item = await _owned_run_item(
        session, guild_id=guild_id, run_item_id=run_item_id, for_update=True
    )
    state = TagSyncState.retry if retryable else TagSyncState.failed
    intent.state = state
    intent.last_error_code = error_code
    intent.last_error_detail = error_detail[:500]
    intent.processing_token = None
    intent.lease_until = None
    if not retryable:
        intent.applied_revision = max(intent.applied_revision, revision)
    if run_item is not None:
        run_item.state = state
        run_item.result_code = error_code
        run_item.error_detail = error_detail[:500]
    await session.commit()
    await session.refresh(intent)
    return intent


async def cancel_member_intents(
    session: AsyncSession, *, guild_id: str, discord_user_id: str
) -> TagSyncIntent | None:
    intent = await _locked_intent(
        session, guild_id=guild_id, discord_user_id=discord_user_id
    )
    if intent is None:
        return None
    intent.desired_revision += 1
    intent.applied_revision = intent.desired_revision
    intent.state = TagSyncState.cancelled
    intent.processing_token = None
    intent.lease_until = None
    intent.last_result = "member_left"
    await session.commit()
    await session.refresh(intent)
    return intent


async def ensure_periodic_run(
    session: AsyncSession, *, guild_id: str, day_key: str
) -> TagSyncRun | None:
    correlation_id = f"tags-periodic:{guild_id}:{day_key}"
    existing = (
        await session.execute(
            select(TagSyncRun).where(
                TagSyncRun.guild_id == guild_id,
                TagSyncRun.correlation_id == correlation_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        run = existing
    else:
        instance = await _tags_instance(session, guild_id=guild_id)
        if (
            instance is None
            or instance.lifecycle != ModuleLifecycle.active
            or instance.published_config_version_id is None
        ):
            return None
        jitter_seconds = int(hashlib.sha256(guild_id.encode()).hexdigest()[:8], 16) % 1801
        run = await create_sync_run(
            session,
            guild_id=guild_id,
            mode=TagSyncRunMode.effective,
            reason="periodic",
            actor_id=None,
            correlation_id=correlation_id,
            due_at=datetime.now(timezone.utc) + timedelta(seconds=jitter_seconds),
        )
    await schedule_task(
        session,
        guild_id=guild_id,
        module_key="tags",
        job_key="tags.retention",
        resource_type="tag_sync_run",
        resource_id=day_key,
        payload={"day_key": day_key},
        due_at=datetime.now(timezone.utc),
        idempotency_key=f"retention:{day_key}",
        correlation_id=correlation_id,
        max_attempts=None,
        commit=True,
    )
    return run


async def purge_expired_runs(
    session: AsyncSession, *, guild_id: str, retention_days: int = 30
) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    run_ids = list(
        (
            await session.execute(
                select(TagSyncRun.id).where(
                    TagSyncRun.guild_id == guild_id,
                    TagSyncRun.status.in_(
                        [
                            TagSyncRunStatus.completed,
                            TagSyncRunStatus.completed_with_errors,
                            TagSyncRunStatus.cancelled,
                            TagSyncRunStatus.failed,
                        ]
                    ),
                    TagSyncRun.finished_at < cutoff,
                )
            )
        ).scalars()
    )
    if run_ids:
        await session.execute(
            delete(TagSyncRunItem).where(
                TagSyncRunItem.guild_id == guild_id,
                TagSyncRunItem.run_id.in_(run_ids),
            )
        )
        await session.execute(
            delete(TagSyncRun).where(
                TagSyncRun.guild_id == guild_id,
                TagSyncRun.id.in_(run_ids),
            )
        )
    await session.commit()
    return {"deleted_runs": len(run_ids), "retention_days": retention_days}


async def member_diagnostics(
    session: AsyncSession, *, guild_id: str, discord_user_id: str
) -> dict:
    identity = await read_base_member_identity(
        session, guild_id=guild_id, discord_user_id=discord_user_id
    )
    intent = await _locked_intent(
        session, guild_id=guild_id, discord_user_id=discord_user_id
    )
    instance, bindings = await effective_bindings(session, guild_id=guild_id)
    return {
        "identity": None
        if identity is None
        else {
            "id": identity.identity_id,
            "status": identity.status,
            "base_nickname": identity.base_nickname,
            "config_version": identity.config_version,
            "fingerprint": identity.fingerprint,
        },
        "intent": intent_dict(intent) if intent else None,
        "published_config_version_id": instance.published_config_version_id if instance else None,
        "bindings": [binding_dict(item) for item in bindings],
    }


async def module_diagnostics(session: AsyncSession, *, guild_id: str) -> dict:
    instance, bindings = await effective_bindings(session, guild_id=guild_id)
    intent_counts = dict(
        (
            await session.execute(
                select(TagSyncIntent.state, func.count(TagSyncIntent.id))
                .where(TagSyncIntent.guild_id == guild_id)
                .group_by(TagSyncIntent.state)
            )
        ).all()
    )
    last_run = (
        await session.execute(
            select(TagSyncRun)
            .where(TagSyncRun.guild_id == guild_id)
            .order_by(TagSyncRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return {
        "lifecycle": instance.lifecycle if instance else ModuleLifecycle.inactive,
        "published_config_version_id": instance.published_config_version_id if instance else None,
        "binding_count": len(bindings),
        "active_binding_count": sum(1 for item in bindings if item.enabled),
        "inactive_binding_count": sum(1 for item in bindings if not item.enabled),
        "intent_counts": {str(key.value if hasattr(key, "value") else key): value for key, value in intent_counts.items()},
        "last_run": run_dict(last_run) if last_run else None,
    }
