from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import ValidationError

from app.domain_modules.adv.schemas import AdvConfig
from app.platform.contracts import (
    ActionContract,
    CapabilityDefinition,
    ConfigurationContract,
    ConfigurationField,
    ConfigurationFieldType,
    JobDefinition,
    LifecyclePolicy,
    ModuleDefinition,
    ModuleManifest,
    NotificationDefinition,
    PanelContract,
)


def _validate_config(data: dict[str, Any]) -> list[str]:
    try:
        AdvConfig.model_validate(data)
    except ValidationError as exc:
        return [
            f"{'.'.join(str(item) for item in error['loc'])}: {error['msg']}"
            for error in exc.errors(include_url=False)
        ]
    return []


def _validate_permission_grants(data: dict[str, Any], grants: list[Any]) -> list[str]:
    errors: list[str] = []
    for grant in grants:
        if grant.capability == "adv.apply" and grant.subject_type != "role":
            errors.append("adv.apply só pode ser concedido a cargos (subject_type=role).")
        if grant.capability == "adv.revoke":
            errors.append("adv.revoke não aceita concessões: fica restrito a administradores.")
    return errors


def _fields() -> tuple[ConfigurationField, ...]:
    defaults = AdvConfig().model_dump(mode="json")
    types = {
        "enabled": ConfigurationFieldType.boolean,
        "panel_channel_id": ConfigurationFieldType.channel,
        "log_channel_id": ConfigurationFieldType.channel,
        "staff_role_ids": ConfigurationFieldType.roles,
    }
    return tuple(
        ConfigurationField(
            key=key,
            label=key.replace("_", " ").title(),
            field_type=types.get(key, ConfigurationFieldType.text),
            default=value,
        )
        for key, value in defaults.items()
    )


class AdvHealthContributor:
    key = "adv-domain"

    async def __call__(self, session: Any, guild_id: str) -> list[dict[str, Any]]:
        from sqlalchemy import func, select

        from app.domain_modules.adv.models import Warning

        since = datetime.now(timezone.utc) - timedelta(hours=24)
        recent = int(
            await session.scalar(
                select(func.count(Warning.id)).where(
                    Warning.guild_id == guild_id,
                    Warning.created_at >= since,
                    Warning.revoked_at.is_(None),
                )
            )
            or 0
        )
        return [
            {
                "status": "OK",
                "code": "adv.recent_activity",
                "summary": f"{recent} advertência(s) aplicada(s) nas últimas 24h.",
                "action": "",
                "checked_at": datetime.now(timezone.utc),
            }
        ]


ADV_CONFIGURATION = ConfigurationContract(
    schema_version=1,
    fields=_fields(),
    validators=(_validate_config,),
)


MODULE_DEFINITION = ModuleDefinition(
    manifest=ModuleManifest(
        key="adv",
        name="Sistema de Advertência",
        description="Registro de advertências aplicadas a membros, com histórico e log.",
        contract_version=1,
        domain_version="1.0.0",
        required_discord_permissions=("view_channel", "send_messages"),
        provided_resources=("warning",),
        runtime_modes=("domain",),
        default_runtime_mode="domain",
    ),
    configuration=ADV_CONFIGURATION,
    capabilities=(
        CapabilityDefinition("adv.configure", administrative=True, admin_bypass=True),
        CapabilityDefinition("adv.apply"),
        CapabilityDefinition("adv.revoke", administrative=True, admin_bypass=True),
    ),
    lifecycle=LifecyclePolicy(requires_published_configuration=True),
    panels=(PanelContract("staff", recovery_policy="automatic"),),
    actions=(
        ActionContract("open_form", "adv.apply", panel_key="staff"),
        ActionContract("submit", "adv.apply", panel_key="staff"),
    ),
    jobs=(JobDefinition("adv.panel.reconcile", max_attempts=5),),
    notifications=(NotificationDefinition("adv.log", ("channel",)),),
    health_checks=(AdvHealthContributor(),),
    permission_validator=_validate_permission_grants,
)
