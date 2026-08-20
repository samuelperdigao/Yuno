from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from app.domain_modules.registration.schemas import RegistrationConfig
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
        RegistrationConfig.model_validate(data)
    except ValidationError as exc:
        return [
            f"{'.'.join(str(item) for item in error['loc'])}: {error['msg']}"
            for error in exc.errors(include_url=False)
        ]
    return []


def _validate_permission_grants(data: dict[str, Any], grants: list[Any]) -> list[str]:
    config = RegistrationConfig.model_validate(data)
    submit = [item for item in grants if item.capability == "registration.submit"]
    review = [item for item in grants if item.capability == "registration.review"]
    errors: list[str] = []
    if len(submit) != 1 or not (
        submit[0].subject_type == "everyone"
        and submit[0].subject_id == ""
        and submit[0].scope_type == "guild"
        and submit[0].scope_id == ""
    ):
        errors.append("registration.submit exige exatamente um grant everyone no escopo da guild.")
    actual_approvers = {
        item.subject_id
        for item in review
        if item.subject_type == "role"
        and item.scope_type == "guild"
        and item.scope_id == ""
    }
    if len(review) != len(actual_approvers) or actual_approvers != set(config.approver_role_ids):
        errors.append("Grants de registration.review devem corresponder aos cargos aprovadores.")
    return errors


def _fields() -> tuple[ConfigurationField, ...]:
    defaults = RegistrationConfig().model_dump(mode="json")
    types = {
        "enabled": ConfigurationFieldType.boolean,
        "panel_channel_id": ConfigurationFieldType.channel,
        "approval_channel_id": ConfigurationFieldType.channel,
        "log_channel_id": ConfigurationFieldType.channel,
        "member_role_id": ConfigurationFieldType.role,
        "approver_role_ids": ConfigurationFieldType.roles,
        "player_id_numeric_only": ConfigurationFieldType.boolean,
        "player_id_min_length": ConfigurationFieldType.number,
        "player_id_max_length": ConfigurationFieldType.number,
        "name_min_length": ConfigurationFieldType.number,
        "name_max_length": ConfigurationFieldType.number,
        "allow_resubmit_after_rejection": ConfigurationFieldType.boolean,
        "panel_color": ConfigurationFieldType.color,
        "panel_banner_url": ConfigurationFieldType.text,
        "panel_thumbnail_url": ConfigurationFieldType.text,
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


class RegistrationMigrationContract:
    key = "registration-v2"

    async def inventory(self, session: Any, guild_id: str) -> dict[str, Any]:
        from app.domain_modules.registration.services import legacy_inventory

        return await legacy_inventory(session, guild_id=guild_id)

    async def validate(self, session: Any, guild_id: str) -> list[str]:
        inventory = await self.inventory(session, guild_id)
        return list(inventory.get("warnings") or [])


class RegistrationHealthContributor:
    key = "registration-domain"

    async def __call__(self, session: Any, guild_id: str) -> list[dict[str, Any]]:
        from sqlalchemy import func, select

        from app.domain_modules.registration.domain import RegistrationRequestStatus
        from app.domain_modules.registration.models import RegistrationRequest

        pending = int(
            await session.scalar(
                select(func.count(RegistrationRequest.id)).where(
                    RegistrationRequest.guild_id == guild_id,
                    RegistrationRequest.status == RegistrationRequestStatus.pending,
                )
            )
            or 0
        )
        processing = int(
            await session.scalar(
                select(func.count(RegistrationRequest.id)).where(
                    RegistrationRequest.guild_id == guild_id,
                    RegistrationRequest.status == RegistrationRequestStatus.processing,
                )
            )
            or 0
        )
        return [
            {
                "status": "WARNING" if processing else "OK",
                "code": "registration.processing",
                "summary": f"{processing} aprovacao(oes) em processamento e {pending} pendente(s).",
                "action": "Execute a recuperacao de claims." if processing else "",
                "checked_at": datetime.now(timezone.utc),
            }
        ]


REGISTRATION_CONFIGURATION = ConfigurationContract(
    schema_version=1,
    fields=_fields(),
    validators=(_validate_config,),
)


MODULE_DEFINITION = ModuleDefinition(
    manifest=ModuleManifest(
        key="registration",
        name="Registro",
        description="Registro tenant-safe de membros com aprovacao administrativa.",
        contract_version=2,
        domain_version="2.0.0",
        required_discord_permissions=(
            "view_channel",
            "send_messages",
            "manage_nicknames",
            "manage_roles",
        ),
        provided_resources=("organization_member", "registration_request"),
        runtime_modes=("domain",),
        default_runtime_mode="domain",
    ),
    configuration=REGISTRATION_CONFIGURATION,
    capabilities=(
        CapabilityDefinition("registration.configure", administrative=True, admin_bypass=True),
        CapabilityDefinition("registration.submit"),
        CapabilityDefinition("registration.review", resource_scoped=True),
        CapabilityDefinition(
            "registration.recover", administrative=True, allow_automation=True, admin_bypass=True
        ),
        CapabilityDefinition(
            "registration.deactivate", administrative=True, allow_automation=True, admin_bypass=True
        ),
    ),
    lifecycle=LifecyclePolicy(requires_published_configuration=True),
    panels=(
        PanelContract("public", recovery_policy="automatic"),
        PanelContract("review", instance_type="resource", recovery_policy="automatic"),
    ),
    actions=(
        ActionContract("open_form", "registration.submit", panel_key="public"),
        ActionContract("submit", "registration.submit", panel_key="public"),
        ActionContract("approve", "registration.review", panel_key="review"),
        ActionContract("reject", "registration.review", panel_key="review"),
        ActionContract("submit_rejection", "registration.review", panel_key="review"),
    ),
    jobs=(
        JobDefinition("registration.processing.recover", max_attempts=10),
        JobDefinition("registration.panel.reconcile", max_attempts=5),
    ),
    notifications=(
        NotificationDefinition("registration.review_request", ("panel",)),
        NotificationDefinition("registration.review_update", ("panel",)),
        NotificationDefinition("registration.log_approved", ("channel",)),
        NotificationDefinition("registration.log_rejected", ("channel",)),
        NotificationDefinition("registration.member_approved", ("user",)),
        NotificationDefinition("registration.member_rejected", ("user",)),
    ),
    health_checks=(RegistrationHealthContributor(),),
    migration=RegistrationMigrationContract(),
    permission_validator=_validate_permission_grants,
)
