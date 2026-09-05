from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from app.domain_modules.ausencia.schemas import AusenciaConfig
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
        AusenciaConfig.model_validate(data)
    except ValidationError as exc:
        return [
            f"{'.'.join(str(item) for item in error['loc'])}: {error['msg']}"
            for error in exc.errors(include_url=False)
        ]
    return []


def _validate_permission_grants(data: dict[str, Any], grants: list[Any]) -> list[str]:
    register = [item for item in grants if item.capability == "ausencia.register"]
    errors: list[str] = []
    if len(register) != 1 or not (
        register[0].subject_type == "everyone"
        and register[0].subject_id == ""
        and register[0].scope_type == "guild"
        and register[0].scope_id == ""
    ):
        errors.append("ausencia.register exige exatamente um grant everyone no escopo da guild.")
    return errors


def _fields() -> tuple[ConfigurationField, ...]:
    defaults = AusenciaConfig().model_dump(mode="json")
    types = {
        "enabled": ConfigurationFieldType.boolean,
        "panel_channel_id": ConfigurationFieldType.channel,
        "log_channel_id": ConfigurationFieldType.channel,
        "max_dias": ConfigurationFieldType.number,
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


class AusenciaHealthContributor:
    key = "ausencia-domain"

    async def __call__(self, session: Any, guild_id: str) -> list[dict[str, Any]]:
        from sqlalchemy import func, select

        from app.domain_modules.ausencia.models import AbsenceRecord

        overdue_pending = int(
            await session.scalar(
                select(func.count(AbsenceRecord.id)).where(
                    AbsenceRecord.guild_id == guild_id,
                    AbsenceRecord.overdue_notified.is_(False),
                    AbsenceRecord.ends_at <= datetime.now(timezone.utc),
                )
            )
            or 0
        )
        return [
            {
                "status": "WARNING" if overdue_pending else "OK",
                "code": "ausencia.overdue_pending",
                "summary": f"{overdue_pending} ausencia(s) vencida(s) aguardando aviso.",
                "action": "A varredura horaria do bot resolve isso automaticamente." if overdue_pending else "",
                "checked_at": datetime.now(timezone.utc),
            }
        ]


AUSENCIA_CONFIGURATION = ConfigurationContract(
    schema_version=1,
    fields=_fields(),
    validators=(_validate_config,),
)


MODULE_DEFINITION = ModuleDefinition(
    manifest=ModuleManifest(
        key="ausencia",
        name="Sistema de Ausência",
        description="Registro de ausencias temporarias com aviso automatico de vencimento.",
        contract_version=1,
        domain_version="1.0.0",
        required_discord_permissions=("view_channel", "send_messages"),
        provided_resources=("absence_record",),
        runtime_modes=("domain",),
        default_runtime_mode="domain",
    ),
    configuration=AUSENCIA_CONFIGURATION,
    capabilities=(
        CapabilityDefinition("ausencia.configure", administrative=True, admin_bypass=True),
        CapabilityDefinition("ausencia.register"),
        CapabilityDefinition(
            "ausencia.notify", administrative=True, allow_automation=True, admin_bypass=True
        ),
    ),
    lifecycle=LifecyclePolicy(requires_published_configuration=True),
    panels=(PanelContract("public", recovery_policy="automatic"),),
    actions=(
        ActionContract("open_form", "ausencia.register", panel_key="public"),
        ActionContract("submit", "ausencia.register", panel_key="public"),
    ),
    jobs=(JobDefinition("ausencia.panel.reconcile", max_attempts=5),),
    notifications=(
        NotificationDefinition("ausencia.confirmation", ("channel",)),
        NotificationDefinition("ausencia.log", ("channel",)),
        NotificationDefinition("ausencia.overdue_reminder", ("user",)),
    ),
    health_checks=(AusenciaHealthContributor(),),
    permission_validator=_validate_permission_grants,
)
