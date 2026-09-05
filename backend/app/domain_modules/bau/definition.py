from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from app.domain_modules.bau.schemas import BauConfig
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
        BauConfig.model_validate(data)
    except ValidationError as exc:
        return [
            f"{'.'.join(str(item) for item in error['loc'])}: {error['msg']}"
            for error in exc.errors(include_url=False)
        ]
    return []


def _validate_permission_grants(data: dict[str, Any], grants: list[Any]) -> list[str]:
    errors: list[str] = []
    for grant in grants:
        if grant.capability == "bau.move_stock" and grant.subject_type != "role":
            errors.append("bau.move_stock só pode ser concedido a cargos (subject_type=role).")
        if grant.capability == "bau.clear_stock":
            errors.append("bau.clear_stock não aceita concessões: fica restrito a administradores.")
    return errors


def _fields() -> tuple[ConfigurationField, ...]:
    defaults = BauConfig().model_dump(mode="json")
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


class BauHealthContributor:
    key = "bau-domain"

    async def __call__(self, session: Any, guild_id: str) -> list[dict[str, Any]]:
        from sqlalchemy import func, select

        from app.domain_modules.bau.models import BauCategory

        categories = int(
            await session.scalar(
                select(func.count(BauCategory.id)).where(BauCategory.guild_id == guild_id)
            )
            or 0
        )
        return [
            {
                "status": "OK" if categories else "WARNING",
                "code": "bau.catalog_seeded",
                "summary": f"{categories} categoria(s) no catálogo." if categories else "Catálogo ainda não foi populado.",
                "action": "" if categories else "Publique a configuração para popular o catálogo padrão.",
                "checked_at": datetime.now(timezone.utc),
            }
        ]


BAU_CONFIGURATION = ConfigurationContract(
    schema_version=1,
    fields=_fields(),
    validators=(_validate_config,),
)


MODULE_DEFINITION = ModuleDefinition(
    manifest=ModuleManifest(
        key="bau",
        name="Baú da Gerência",
        description="Controle de inventário e estoque compartilhado da organização.",
        contract_version=1,
        domain_version="1.0.0",
        required_discord_permissions=("view_channel", "send_messages"),
        provided_resources=("bau_category", "bau_item", "bau_stock"),
        runtime_modes=("domain",),
        default_runtime_mode="domain",
    ),
    configuration=BAU_CONFIGURATION,
    capabilities=(
        CapabilityDefinition("bau.configure", administrative=True, admin_bypass=True),
        CapabilityDefinition("bau.manage_catalog", administrative=True, admin_bypass=True),
        CapabilityDefinition("bau.move_stock", administrative=True, admin_bypass=True),
        CapabilityDefinition("bau.clear_stock", administrative=True, admin_bypass=True),
    ),
    lifecycle=LifecyclePolicy(requires_published_configuration=True),
    panels=(PanelContract("stock", recovery_policy="automatic"),),
    actions=(
        ActionContract("select_category", "bau.move_stock", panel_key="stock"),
        ActionContract("submit_movement", "bau.move_stock", panel_key="stock"),
    ),
    jobs=(JobDefinition("bau.panel.reconcile", max_attempts=5),),
    notifications=(NotificationDefinition("bau.log", ("channel",)),),
    health_checks=(BauHealthContributor(),),
    permission_validator=_validate_permission_grants,
)
