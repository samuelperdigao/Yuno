from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from app.domain_modules.meta.domain import CycleState, GoalState
from app.domain_modules.meta.models import MetaCycle, MetaGoal
from app.platform.contracts import (
    CapabilityDefinition,
    ConfigurationContract,
    JobDefinition,
    LifecyclePolicy,
    ModuleDefinition,
    ModuleManifest,
)


class MetaHealthContributor:
    key = "meta-domain"

    async def __call__(self, session: Any, guild_id: str) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        active = int(
            await session.scalar(
                select(func.count(MetaCycle.id)).where(
                    MetaCycle.guild_id == guild_id,
                    MetaCycle.state == CycleState.active,
                )
            )
            or 0
        )
        pending = int(
            await session.scalar(
                select(func.count(MetaCycle.id)).where(
                    MetaCycle.guild_id == guild_id,
                    MetaCycle.state == CycleState.launch_pending,
                )
            )
            or 0
        )
        action_required = int(
            await session.scalar(
                select(func.count(MetaGoal.id)).where(
                    MetaGoal.guild_id == guild_id,
                    MetaGoal.state == GoalState.action_required,
                )
            )
            or 0
        )
        return [
            {
                "status": "WARNING" if pending or action_required else "OK",
                "code": "meta.transitions",
                "summary": f"{active} ciclo(s) ativo(s), {pending} lancamento(s) pendente(s).",
                "detail": f"{action_required} Meta(s) exigem recuperacao interna.",
                "action": "Verifique o worker e as permissoes do canal." if action_required else "",
                "checked_at": now,
            }
        ]


MODULE_DEFINITION = ModuleDefinition(
    manifest=ModuleManifest(
        key="meta",
        name="Sistema de Metas",
        description="Metas recorrentes e personalizadas com participantes e objetivos congelados por ciclo.",
        contract_version=2,
        domain_version="2.0.0",
        required_discord_permissions=(
            "view_channel",
            "send_messages",
            "read_message_history",
            "mention_everyone",
        ),
        provided_resources=(
            "meta_product",
            "meta_goal",
            "meta_goal_config_version",
            "meta_cycle",
            "meta_integration_event",
        ),
        runtime_modes=("domain",),
        default_runtime_mode="domain",
    ),
    configuration=ConfigurationContract(schema_version=2),
    capabilities=(
        CapabilityDefinition("meta.configure", administrative=True, admin_bypass=True),
        CapabilityDefinition("meta.manage_goals", administrative=True, admin_bypass=True),
        CapabilityDefinition(
            "meta.run_transitions", administrative=True, allow_automation=True, admin_bypass=True
        ),
        CapabilityDefinition("meta.read_contracts", allow_automation=True),
    ),
    lifecycle=LifecyclePolicy(requires_published_configuration=False),
    jobs=(
        JobDefinition("meta.goal.launch", max_attempts=10),
        JobDefinition("meta.cycle.transition", max_attempts=10),
        JobDefinition("meta.notice.reconcile", max_attempts=10),
        JobDefinition("meta.recovery", max_attempts=10),
    ),
    health_checks=(MetaHealthContributor(),),
)
