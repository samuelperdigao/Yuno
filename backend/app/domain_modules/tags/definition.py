from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select, update

from app.domain_modules.tags.domain import (
    TagSyncRunMode,
    TagSyncRunStatus,
    TagSyncState,
    normalize_snowflake,
    normalize_tag,
)
from app.domain_modules.tags.models import (
    TagRoleBindingDraft,
    TagRoleBindingVersion,
    TagSyncIntent,
    TagSyncRun,
    TagSyncRunItem,
)
from app.platform.contracts import (
    CapabilityDefinition,
    ConfigurationContract,
    JobDefinition,
    LifecyclePolicy,
    ModuleDefinition,
    ModuleDependency,
    ModuleManifest,
)
from app.platform.automation import schedule_task
from app.platform.models import ModuleLifecycle


class TagsRelationalConfigurationParticipant:
    async def validate_draft(
        self, session: Any, *, guild_id: str, instance: Any, draft: Any
    ) -> list[str]:
        bindings = list(
            (
                await session.execute(
                    select(TagRoleBindingDraft).where(
                        TagRoleBindingDraft.guild_id == guild_id,
                        TagRoleBindingDraft.module_instance_id == instance.id,
                    )
                )
            ).scalars()
        )
        errors: list[str] = []
        seen: set[str] = set()
        for binding in bindings:
            try:
                role_id = normalize_snowflake(binding.discord_role_id, field="Cargo")
                normalize_tag(binding.tag)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if role_id == guild_id:
                errors.append("O cargo @everyone nao pode receber Tag.")
            if role_id in seen:
                errors.append(f"O cargo {role_id} aparece mais de uma vez.")
            seen.add(role_id)
        return errors

    async def materialize_version(
        self, session: Any, *, guild_id: str, instance: Any, draft: Any, version: Any
    ) -> None:
        bindings = list(
            (
                await session.execute(
                    select(TagRoleBindingDraft).where(
                        TagRoleBindingDraft.guild_id == guild_id,
                        TagRoleBindingDraft.module_instance_id == instance.id,
                    )
                )
            ).scalars()
        )
        session.add_all(
            [
                TagRoleBindingVersion(
                    config_version_id=version.id,
                    module_instance_id=instance.id,
                    guild_id=guild_id,
                    discord_role_id=item.discord_role_id,
                    tag=item.tag,
                    enabled=item.enabled,
                )
                for item in bindings
            ]
        )
        if instance.lifecycle == ModuleLifecycle.active:
            active = (
                await session.execute(
                    select(TagSyncRun).where(
                        TagSyncRun.guild_id == guild_id,
                        TagSyncRun.status.in_(
                            [TagSyncRunStatus.pending, TagSyncRunStatus.planning, TagSyncRunStatus.running]
                        ),
                    ).with_for_update()
                )
            ).scalars().first()
            now = datetime.now(timezone.utc)
            if active is not None:
                # A versao nova substitui o run anterior. Membros ja iniciados
                # terminam com uma revisao menor; o novo run os agenda outra vez
                # e a revisao monotônica garante que o estado publicado mais
                # recente seja o ultimo a convergir.
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
                    .values(state=TagSyncState.cancelled, result_code="superseded_by_config")
                )
                await session.flush()
            reason = "config_rolled_back" if version.source_version is not None else "config_published"
            run = TagSyncRun(
                guild_id=guild_id,
                mode=TagSyncRunMode.effective,
                reason=reason,
                config_version_id=version.id,
                requested_by=version.published_by,
                correlation_id=f"tags-publish:{guild_id}:{version.id}",
            )
            session.add(run)
            await session.flush()
            await schedule_task(
                session,
                guild_id=guild_id,
                module_key="tags",
                job_key="tags.run.plan",
                resource_type="tag_sync_run",
                resource_id=run.id,
                payload={"run_id": run.id},
                due_at=now,
                idempotency_key=f"run:{run.id}:plan:start",
                correlation_id=run.correlation_id,
                max_attempts=None,
                commit=False,
            )

    async def restore_version(
        self, session: Any, *, guild_id: str, instance: Any, draft: Any, source: Any
    ) -> None:
        await session.execute(
            delete(TagRoleBindingDraft).where(
                TagRoleBindingDraft.guild_id == guild_id,
                TagRoleBindingDraft.module_instance_id == instance.id,
            )
        )
        await session.flush()
        source_bindings = list(
            (
                await session.execute(
                    select(TagRoleBindingVersion).where(
                        TagRoleBindingVersion.guild_id == guild_id,
                        TagRoleBindingVersion.module_instance_id == instance.id,
                        TagRoleBindingVersion.config_version_id == source.id,
                    )
                )
            ).scalars()
        )
        session.add_all(
            [
                TagRoleBindingDraft(
                    module_instance_id=instance.id,
                    guild_id=guild_id,
                    discord_role_id=item.discord_role_id,
                    tag=item.tag,
                    enabled=item.enabled,
                    created_by=draft.updated_by or source.published_by,
                    updated_by=draft.updated_by or source.published_by,
                )
                for item in source_bindings
            ]
        )


class TagsHealthContributor:
    key = "tags-domain"

    async def __call__(self, session: Any, guild_id: str) -> list[dict[str, Any]]:
        pending = int(
            await session.scalar(
                select(func.count(TagSyncIntent.id)).where(
                    TagSyncIntent.guild_id == guild_id,
                    TagSyncIntent.state.in_(["pending", "processing", "retry"]),
                )
            )
            or 0
        )
        active_runs = int(
            await session.scalar(
                select(func.count(TagSyncRun.id)).where(
                    TagSyncRun.guild_id == guild_id,
                    TagSyncRun.status.in_(
                        [TagSyncRunStatus.pending, TagSyncRunStatus.planning, TagSyncRunStatus.running]
                    ),
                )
            )
            or 0
        )
        return [
            {
                "status": "WARNING" if pending > 1000 or active_runs > 1 else "OK",
                "code": "tags.reconciliation",
                "summary": f"{pending} membro(s) pendente(s) e {active_runs} run(s) ativo(s).",
                "action": "Verifique os runs e bloqueios." if pending > 1000 else "",
                "checked_at": datetime.now(timezone.utc),
            }
        ]


TAGS_CONFIGURATION = ConfigurationContract(schema_version=1)


MODULE_DEFINITION = ModuleDefinition(
    manifest=ModuleManifest(
        key="tags",
        name="Sistema de Tags",
        description="Resolve uma Tag pela hierarquia ao vivo e reconcilia nicknames registrados.",
        contract_version=1,
        domain_version="1.0.0",
        dependencies=(ModuleDependency("registration", minimum_contract_version=2),),
        required_discord_permissions=("manage_nicknames",),
        provided_resources=("tag_binding", "tag_sync_intent", "tag_sync_run"),
        runtime_modes=("domain",),
        default_runtime_mode="domain",
    ),
    configuration=TAGS_CONFIGURATION,
    capabilities=(
        CapabilityDefinition("tags.configure", administrative=True, admin_bypass=True),
        CapabilityDefinition("tags.sync", administrative=True, allow_automation=True, admin_bypass=True),
        CapabilityDefinition("tags.diagnose", administrative=True, allow_automation=True, admin_bypass=True),
    ),
    lifecycle=LifecyclePolicy(requires_published_configuration=True),
    jobs=(
        JobDefinition("tags.member.sync", max_attempts=8),
        JobDefinition("tags.run.plan", max_attempts=8),
        JobDefinition("tags.run.finalize", max_attempts=8),
        JobDefinition("tags.retention", max_attempts=5),
    ),
    health_checks=(TagsHealthContributor(),),
    relational_configuration=TagsRelationalConfigurationParticipant(),
)
