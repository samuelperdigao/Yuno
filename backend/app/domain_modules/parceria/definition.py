from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from app.domain_modules.parceria.domain import ParceriaStatus, RegistrationAttemptStatus
from app.domain_modules.parceria.migration import ParceriaMigration
from app.domain_modules.parceria.models import Parceria, RegistrationAttempt
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
from app.platform.automation import schedule_task


MANAGER_CAPABILITIES = (
    "parceria.register",
    "parceria.edit",
    "parceria.deactivate",
)


def _validate_roles(data: dict[str, Any], grants: list[Any]) -> list[str]:
    configured = set(data.get("manager_role_ids") or [])
    errors: list[str] = []
    for capability in MANAGER_CAPABILITIES:
        roles = {
            item.subject_id
            for item in grants
            if item.capability == capability
            and item.subject_type == "role"
            and item.scope_type == "guild"
            and not item.scope_id
        }
        matching = [item for item in grants if item.capability == capability]
        if roles != configured or len(matching) != len(roles):
            errors.append(f"Grants de {capability} devem corresponder aos cargos gerentes publicados.")
    return errors


class ParceriaHealth:
    key = "parceria-domain"

    async def __call__(self, session: Any, guild_id: str) -> list[dict[str, Any]]:
        pending = int(await session.scalar(select(func.count()).select_from(Parceria).where(Parceria.guild_id == guild_id, Parceria.status.in_([ParceriaStatus.publication_pending, ParceriaStatus.degraded]))) or 0)
        expired = int(await session.scalar(select(func.count()).select_from(RegistrationAttempt).where(RegistrationAttempt.guild_id == guild_id, RegistrationAttempt.status == RegistrationAttemptStatus.expired)) or 0)
        return [{"status": "WARNING" if pending else "OK", "code": "parceria.publication", "summary": f"{pending} publicação(ões) pendente(s) ou degradada(s).", "detail": f"{expired} sessão(ões) expirada(s).", "action": "Execute a reconciliação de Parcerias." if pending else "", "checked_at": datetime.now(timezone.utc)}]


class ParceriaConfigurationParticipant:
    async def validate_draft(self, session: Any, *, guild_id: str, instance: Any, draft: Any) -> list[str]:
        del session, guild_id, instance, draft
        return []

    async def materialize_version(self, session: Any, *, guild_id: str, instance: Any, draft: Any, version: Any) -> None:
        del instance, draft
        now = datetime.now(timezone.utc)
        for job_key in (
            "parceria.registration.expire",
            "parceria.panel.reconcile",
            "parceria.publication.reconcile",
            "parceria.publication.retry",
        ):
            await schedule_task(
                session,
                guild_id=guild_id,
                module_key="parceria",
                job_key=job_key,
                resource_type="guild",
                resource_id=guild_id,
                payload={"config_version_id": version.id, "reason": "config_published"},
                due_at=now,
                idempotency_key=f"parceria:config:{version.id}:{job_key}",
                correlation_id=f"parceria-config:{guild_id}:{version.id}",
                max_attempts=None,
                commit=False,
            )

    async def restore_version(self, session: Any, *, guild_id: str, instance: Any, draft: Any, source: Any) -> None:
        del session, guild_id, instance, draft, source


PARTNERSHIP_CONFIGURATION = ConfigurationContract(
    schema_version=1,
    fields=(
        ConfigurationField("registrar_channel_id", "Canal de registro", ConfigurationFieldType.channel, required=True),
        ConfigurationField("ativas_channel_id", "Canal de parcerias ativas", ConfigurationFieldType.channel, required=True),
        ConfigurationField("manager_role_ids", "Cargos gerentes", ConfigurationFieldType.roles, required=True, constraints={"min_length": 1, "max_length": 25}),
        ConfigurationField("category_id", "Categoria", ConfigurationFieldType.category, required=False),
        ConfigurationField("log_channel_id", "Canal de logs", ConfigurationFieldType.channel, required=False),
    ),
)


MODULE_DEFINITION = ModuleDefinition(
    manifest=ModuleManifest(
        key="parceria",
        name="Parcerias",
        description="Cadastro, edição e publicação idempotente de parcerias por guild.",
        contract_version=2,
        domain_version="1.0.0",
        minimum_plan="basico",
        required_discord_permissions=("view_channel", "send_messages", "read_message_history", "attach_files", "embed_links", "manage_messages"),
        provided_resources=("parceria", "parceria_family", "parceria_registration_attempt", "parceria_publication"),
        runtime_modes=("domain",),
        default_runtime_mode="domain",
    ),
    configuration=PARTNERSHIP_CONFIGURATION,
    capabilities=(
        CapabilityDefinition("parceria.configure", administrative=True),
        CapabilityDefinition("parceria.register"),
        CapabilityDefinition("parceria.edit", resource_scoped=True),
        CapabilityDefinition("parceria.deactivate", resource_scoped=True),
        CapabilityDefinition("parceria.diagnose", administrative=True),
        CapabilityDefinition("parceria.automation", allow_automation=True, denial_reason="Somente automação."),
    ),
    lifecycle=LifecyclePolicy(requires_published_configuration=True),
    panels=(PanelContract("global", recovery_policy="automatic"),),
    actions=(
        ActionContract("register", "parceria.register", panel_key="global"),
        ActionContract("edit", "parceria.edit", panel_key="global"),
        ActionContract("deactivate", "parceria.deactivate", panel_key="global"),
    ),
    jobs=(
        JobDefinition("parceria.registration.expire", max_attempts=3),
        JobDefinition("parceria.panel.reconcile", max_attempts=5),
        JobDefinition("parceria.publication.reconcile", max_attempts=5),
        JobDefinition("parceria.publication.retry", max_attempts=5),
    ),
    notifications=(
        NotificationDefinition("parceria.publication", ("channel",)),
        NotificationDefinition("parceria.panel", ("channel",)),
        NotificationDefinition("parceria.log", ("channel",)),
    ),
    health_checks=(ParceriaHealth(),),
    migration=ParceriaMigration(),
    permission_validator=_validate_roles,
    relational_configuration=ParceriaConfigurationParticipant(),
)
