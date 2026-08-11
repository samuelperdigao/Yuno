from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

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


class FarmMigrationContract:
    """Declara o corte controlado; o inventario tenant-safe vive na API do modulo."""

    key = "farm-v2"

    async def inventory(self, session: Any, guild_id: str) -> dict[str, Any]:
        from app.domain_modules.farm.services import legacy_inventory

        return await legacy_inventory(session, guild_id=guild_id)

    async def validate(self, session: Any, guild_id: str) -> list[str]:
        inventory = await self.inventory(session, guild_id)
        return list(inventory.get("warnings") or [])


class FarmHealthContributor:
    key = "farm-domain"

    async def __call__(self, session: Any, guild_id: str) -> list[dict[str, Any]]:
        from sqlalchemy import func, select

        from app.domain_modules.farm.domain import CycleStatus, SubmissionStatus
        from app.domain_modules.farm.models import FarmCycle, FarmSubmission

        active = int(await session.scalar(select(func.count(FarmCycle.id)).where(FarmCycle.guild_id == guild_id, FarmCycle.status == CycleStatus.active)) or 0)
        pending = int(await session.scalar(select(func.count(FarmSubmission.id)).where(FarmSubmission.guild_id == guild_id, FarmSubmission.status.in_([SubmissionStatus.submitted, SubmissionStatus.under_review]))) or 0)
        now = datetime.now(timezone.utc)
        return [
            {"status": "WARNING" if active > 1 else "OK", "code": "farm.active_cycles", "summary": f"{active} ciclo(s) ativo(s).", "action": "Mantenha no maximo um ciclo ativo." if active > 1 else "", "checked_at": now},
            {"status": "WARNING" if pending else "OK", "code": "farm.review_queue", "summary": f"{pending} entrega(s) aguardando revisao.", "action": "Abra o painel de revisao." if pending else "", "checked_at": now},
        ]


def _validate_ticket_categories(data: dict[str, Any]) -> list[str]:
    values = data.get("ticket_category_ids")
    if not isinstance(values, list) or not values:
        return ["Selecione ao menos uma categoria de tickets."]
    if len(values) > 10 or not all(isinstance(item, str) and item for item in values):
        return ["Categorias de tickets devem conter de 1 a 10 IDs validos."]
    if len(values) != len(set(values)):
        return ["Categoria de tickets duplicada."]
    return []


FARM_CONFIGURATION = ConfigurationContract(
    schema_version=1,
    fields=(
        ConfigurationField("timezone", "Fuso horario", ConfigurationFieldType.timezone, required=True, default="America/Sao_Paulo"),
        ConfigurationField("ticket_category_ids", "Categorias dos tickets", ConfigurationFieldType.collection, required=True),
        ConfigurationField("public_panel_channel_id", "Canal do painel publico", ConfigurationFieldType.channel, required=True),
        ConfigurationField("review_panel_channel_id", "Canal da fila de revisao", ConfigurationFieldType.channel, required=True),
        ConfigurationField("log_channel_id", "Canal de logs", ConfigurationFieldType.channel),
        ConfigurationField("proof_required", "Exigir comprovante", ConfigurationFieldType.boolean, required=True, default=True),
        ConfigurationField("panel_title", "Titulo do painel", ConfigurationFieldType.text, required=True, default="Central de Farm", constraints={"max_length": 256}),
        ConfigurationField("panel_description", "Descricao do painel", ConfigurationFieldType.text, required=True, default="Acompanhe seus ciclos e entregas.", constraints={"max_length": 4096}),
        ConfigurationField("panel_color", "Cor do painel", ConfigurationFieldType.color, required=True, default="#FFC72C"),
    ),
    validators=(_validate_ticket_categories,),
)


CAPABILITIES = (
    CapabilityDefinition("farm.configure", administrative=True, admin_bypass=True),
    CapabilityDefinition("farm.manage_catalog", administrative=True, admin_bypass=True),
    CapabilityDefinition("farm.manage_cycles", administrative=True, admin_bypass=True),
    CapabilityDefinition("farm.open_own_ticket"),
    CapabilityDefinition("farm.open_ticket_for_member", administrative=True, admin_bypass=True),
    CapabilityDefinition("farm.submit_own", resource_scoped=True, allow_resource_owner=True),
    CapabilityDefinition("farm.review", administrative=True, resource_scoped=True, admin_bypass=True),
    CapabilityDefinition("farm.view_all", administrative=True, resource_scoped=True, admin_bypass=True),
    CapabilityDefinition("farm.close_cycle", administrative=True, resource_scoped=True, allow_automation=True, admin_bypass=True),
    CapabilityDefinition("farm.recover_panels", administrative=True, allow_automation=True, admin_bypass=True),
)


MODULE_DEFINITION = ModuleDefinition(
    manifest=ModuleManifest(
        key="farm",
        name="Farm",
        description="Ciclos configuraveis de entregas, revisao e progresso.",
        contract_version=1,
        domain_version="2.0.0",
        required_discord_permissions=(
            "view_channel",
            "send_messages",
            "embed_links",
            "attach_files",
            "manage_channels",
            "manage_messages",
        ),
        provided_resources=("product", "template", "cycle", "ticket", "submission", "review"),
        runtime_modes=("legacy", "shadow", "domain"),
        default_runtime_mode="legacy",
    ),
    configuration=FARM_CONFIGURATION,
    capabilities=CAPABILITIES,
    lifecycle=LifecyclePolicy(requires_published_configuration=True),
    panels=(
        PanelContract("public", recovery_policy="automatic"),
        PanelContract("ticket", instance_type="resource", recovery_policy="automatic"),
        PanelContract("review", recovery_policy="automatic"),
    ),
    actions=(
        ActionContract("open_own_ticket", "farm.open_own_ticket", panel_key="public"),
        ActionContract("view_own", "farm.open_own_ticket", panel_key="public"),
        ActionContract("open_for_member", "farm.open_ticket_for_member", panel_key="public"),
        ActionContract("submit_own", "farm.submit_own", panel_key="ticket"),
        ActionContract("progress", "farm.submit_own", panel_key="ticket"),
        ActionContract("review_queue", "farm.review", panel_key="review"),
        ActionContract("close_cycle", "farm.close_cycle"),
    ),
    jobs=(
        JobDefinition("farm.cycle.start", max_attempts=5),
        JobDefinition("farm.cycle.begin_closing", max_attempts=5),
        JobDefinition("farm.cycle.finish_closing", max_attempts=10),
        JobDefinition("farm.panel.reconcile", max_attempts=5),
    ),
    notifications=(
        NotificationDefinition("farm.audit", ("channel",)),
        NotificationDefinition("farm.review_pending", ("channel",)),
    ),
    health_checks=(FarmHealthContributor(),),
    migration=FarmMigrationContract(),
)
