from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from app.domain_modules.farm_tickets.domain import (
    ACTIVE_OPERATION_STATUSES,
    OperationStatus,
)
from app.domain_modules.farm_tickets.models import (
    FarmTicket,
    FarmTicketPendingOperation,
)
from app.platform.automation import schedule_task
from app.platform.contracts import (
    ActionContract,
    CapabilityDefinition,
    ConfigurationContract,
    ConfigurationField,
    ConfigurationFieldType,
    JobDefinition,
    LifecyclePolicy,
    ModuleDefinition,
    ModuleDependency,
    ModuleManifest,
    NotificationDefinition,
    PanelContract,
)

TICKETS_CONFIGURATION = ConfigurationContract(
    schema_version=2,
    fields=(
        ConfigurationField(
            "category_id",
            "Categoria principal",
            ConfigurationFieldType.category,
            required=True,
            description="Categoria inicial para os canais de Tickets de Farm.",
        ),
        ConfigurationField(
            "panel_channel_id",
            "Canal do painel",
            ConfigurationFieldType.channel,
            required=True,
        ),
        ConfigurationField(
            "log_channel_id",
            "Canal de logs",
            ConfigurationFieldType.channel,
            required=True,
        ),
        ConfigurationField(
            "administrator_role_ids",
            "Cargos administradores de Tickets",
            ConfigurationFieldType.roles,
            required=True,
            constraints={"min_length": 1},
            description=(
                "Cargos publicados que podem recolher, assumir, aprovar, finalizar e excluir. "
                "manage_guild sozinho nao concede operacao de Tickets."
            ),
        ),
    ),
)


ADMIN_CAPABILITIES = (
    "farm_tickets.open_for_member",
    "farm_tickets.submit",
    "farm_tickets.edit",
    "farm_tickets.read_proofs",
    "farm_tickets.withdraw",
    "farm_tickets.assign",
    "farm_tickets.approve",
    "farm_tickets.finalize",
    "farm_tickets.delete",
)


def _validate_permission_grants(data: dict[str, Any], grants: list[Any]) -> list[str]:
    configured_roles = set(data.get("administrator_role_ids") or [])
    errors: list[str] = []
    open_own = [item for item in grants if item.capability == "farm_tickets.open_own"]
    if len(open_own) != 1 or not (
        open_own[0].subject_type == "everyone"
        and open_own[0].subject_id == ""
        and open_own[0].scope_type == "guild"
        and open_own[0].scope_id == ""
    ):
        errors.append(
            "farm_tickets.open_own exige um grant everyone no escopo da guild."
        )
    for capability in ADMIN_CAPABILITIES:
        matching = [item for item in grants if item.capability == capability]
        roles = {
            item.subject_id
            for item in matching
            if item.subject_type == "role"
            and item.scope_type == "guild"
            and item.scope_id == ""
        }
        if len(matching) != len(roles) or roles != configured_roles:
            errors.append(
                f"Grants de {capability} devem corresponder aos cargos administradores publicados."
            )
    return errors


class FarmTicketsHealthContributor:
    key = "farm-tickets-v2-domain"

    async def __call__(self, session: Any, guild_id: str) -> list[dict[str, Any]]:
        active_operations = int(
            await session.scalar(
                select(func.count(FarmTicketPendingOperation.id)).where(
                    FarmTicketPendingOperation.guild_id == guild_id,
                    FarmTicketPendingOperation.status.in_(
                        list(ACTIVE_OPERATION_STATUSES)
                    ),
                )
            )
            or 0
        )
        retrying = int(
            await session.scalar(
                select(func.count(FarmTicketPendingOperation.id)).where(
                    FarmTicketPendingOperation.guild_id == guild_id,
                    FarmTicketPendingOperation.status == OperationStatus.RETRYING_PROOF,
                )
            )
            or 0
        )
        provisioning_errors = int(
            await session.scalar(
                select(func.count(FarmTicket.id)).where(
                    FarmTicket.guild_id == guild_id,
                    FarmTicket.provisioning_error.is_not(None),
                    FarmTicket.binding_released_at.is_(None),
                )
            )
            or 0
        )
        warning = bool(retrying or provisioning_errors)
        return [
            {
                "status": "WARNING" if warning else "OK",
                "code": "farm_tickets.runtime",
                "summary": f"{active_operations} operacao(oes) ativa(s), {retrying} em retry.",
                "detail": f"{provisioning_errors} ticket(s) com erro de provisioning.",
                "action": "Execute o diagnostico e a reconciliacao." if warning else "",
                "checked_at": datetime.now(timezone.utc),
            }
        ]


class FarmTicketsConfigurationParticipant:
    async def validate_draft(
        self, session: Any, *, guild_id: str, instance: Any, draft: Any
    ) -> list[str]:
        return []

    async def materialize_version(
        self, session: Any, *, guild_id: str, instance: Any, draft: Any, version: Any
    ) -> None:
        await schedule_task(
            session,
            guild_id=guild_id,
            module_key="farm_tickets",
            job_key="farm_tickets.reconcile",
            resource_type="guild",
            resource_id=guild_id,
            payload={"config_version_id": version.id, "reason": "config_published"},
            due_at=datetime.now(timezone.utc),
            idempotency_key=f"farm-tickets:config:{version.id}:reconcile",
            correlation_id=f"farm-tickets-config:{version.id}",
            max_attempts=None,
            commit=False,
        )

    async def restore_version(
        self, session: Any, *, guild_id: str, instance: Any, draft: Any, source: Any
    ) -> None:
        return None


MODULE_DEFINITION = ModuleDefinition(
    manifest=ModuleManifest(
        key="farm_tickets",
        name="Tickets de Farm",
        description="Lancamentos comprovados e recolhimentos FIFO vinculados aos ciclos de Metas.",
        contract_version=2,
        domain_version="2.0.0",
        dependencies=(
            ModuleDependency("meta", minimum_contract_version=2),
            ModuleDependency("registration", minimum_contract_version=2),
        ),
        required_discord_permissions=(
            "view_channel",
            "send_messages",
            "read_message_history",
            "manage_channels",
            "manage_threads",
            "attach_files",
        ),
        provided_resources=(
            "farm_ticket",
            "farm_ticket_entry",
            "farm_ticket_proof",
            "farm_ticket_withdrawal",
        ),
        runtime_modes=("domain",),
        default_runtime_mode="domain",
    ),
    configuration=TICKETS_CONFIGURATION,
    capabilities=(
        CapabilityDefinition("farm_tickets.configure", administrative=True),
        CapabilityDefinition(
            "farm_tickets.open_own", resource_scoped=True, allow_resource_owner=True
        ),
        CapabilityDefinition("farm_tickets.open_for_member", resource_scoped=True),
        CapabilityDefinition(
            "farm_tickets.submit", resource_scoped=True, allow_resource_owner=True
        ),
        CapabilityDefinition(
            "farm_tickets.edit", resource_scoped=True, allow_resource_owner=True
        ),
        CapabilityDefinition(
            "farm_tickets.read_proofs", resource_scoped=True, allow_resource_owner=True
        ),
        CapabilityDefinition("farm_tickets.withdraw", resource_scoped=True),
        CapabilityDefinition("farm_tickets.assign", resource_scoped=True),
        CapabilityDefinition("farm_tickets.approve", resource_scoped=True),
        CapabilityDefinition("farm_tickets.finalize", resource_scoped=True),
        CapabilityDefinition("farm_tickets.delete", resource_scoped=True),
        CapabilityDefinition(
            "farm_tickets.automation",
            allow_automation=True,
            denial_reason="Somente automacao.",
        ),
        CapabilityDefinition("farm_tickets.diagnose", administrative=True),
    ),
    lifecycle=LifecyclePolicy(requires_published_configuration=True),
    panels=(
        PanelContract("global", recovery_policy="automatic"),
        PanelContract("ticket", instance_type="resource", recovery_policy="automatic"),
    ),
    actions=(
        ActionContract("open_ticket", "farm_tickets.open_own", panel_key="global"),
        ActionContract(
            "open_for_member", "farm_tickets.open_for_member", panel_key="global"
        ),
        ActionContract(
            "delete_ticket_global", "farm_tickets.delete", panel_key="global"
        ),
        ActionContract("create_entry", "farm_tickets.submit", panel_key="ticket"),
        ActionContract("edit_entry", "farm_tickets.edit", panel_key="ticket"),
        ActionContract("list_proofs", "farm_tickets.read_proofs", panel_key="ticket"),
        ActionContract("withdraw", "farm_tickets.withdraw", panel_key="ticket"),
        ActionContract("assign", "farm_tickets.assign", panel_key="ticket"),
        ActionContract("approve", "farm_tickets.approve", panel_key="ticket"),
        ActionContract("finalize", "farm_tickets.finalize", panel_key="ticket"),
    ),
    jobs=(
        JobDefinition("farm_tickets.provision", max_attempts=10),
        JobDefinition(
            "farm_tickets.proof.process", timeout_seconds=120, max_attempts=10
        ),
        JobDefinition("farm_tickets.operation.expire", max_attempts=10),
        JobDefinition("farm_tickets.meta.consume", max_attempts=10),
        JobDefinition("farm_tickets.reconcile", max_attempts=10),
        JobDefinition("farm_tickets.storage.cleanup", max_attempts=10),
    ),
    notifications=(
        NotificationDefinition("farm_tickets.panel", ("panel",)),
        NotificationDefinition("farm_tickets.log", ("channel",)),
        NotificationDefinition("farm_tickets.proof_copy", ("thread",)),
        NotificationDefinition("farm_tickets.event", ("thread",)),
    ),
    health_checks=(FarmTicketsHealthContributor(),),
    permission_validator=_validate_permission_grants,
    relational_configuration=FarmTicketsConfigurationParticipant(),
)
