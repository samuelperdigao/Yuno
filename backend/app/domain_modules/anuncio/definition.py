from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.domain_modules.anuncio.schemas import AnuncioConfig
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
    PanelContract,
)


def _validate_config(data: dict[str, Any]) -> list[str]:
    try:
        AnuncioConfig.model_validate(data)
    except ValidationError as exc:
        return [
            f"{'.'.join(str(item) for item in error['loc'])}: {error['msg']}"
            for error in exc.errors(include_url=False)
        ]
    return []


def _fields() -> tuple[ConfigurationField, ...]:
    defaults = AnuncioConfig().model_dump(mode="json")
    types = {
        "enabled": ConfigurationFieldType.boolean,
        "channel_id": ConfigurationFieldType.channel,
        "log_channel_id": ConfigurationFieldType.channel,
        "authorized_role_ids": ConfigurationFieldType.roles,
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


ANUNCIO_CONFIGURATION = ConfigurationContract(
    schema_version=1,
    fields=_fields(),
    validators=(_validate_config,),
)


MODULE_DEFINITION = ModuleDefinition(
    manifest=ModuleManifest(
        key="anuncio",
        name="Sistema de Anúncio",
        description=(
            "Painel fixo para publicar anúncios oficiais no canal do servidor, "
            "com aviso automático no canal de log."
        ),
        contract_version=1,
        domain_version="1.0.0",
        required_discord_permissions=("view_channel", "send_messages", "attach_files"),
        provided_resources=(),
        runtime_modes=("domain",),
        default_runtime_mode="domain",
    ),
    configuration=ANUNCIO_CONFIGURATION,
    capabilities=(
        CapabilityDefinition("anuncio.configure", administrative=True, admin_bypass=True),
        CapabilityDefinition(
            "anuncio.publish",
            admin_bypass=True,
            denial_reason="Você não tem um cargo autorizado a publicar anúncios.",
        ),
    ),
    lifecycle=LifecyclePolicy(requires_published_configuration=True),
    panels=(PanelContract("public", recovery_policy="automatic"),),
    actions=(
        ActionContract("open_form", "anuncio.publish", panel_key="public"),
        ActionContract("submit", "anuncio.publish", panel_key="public"),
    ),
    jobs=(JobDefinition("anuncio.panel.reconcile", max_attempts=5),),
)
