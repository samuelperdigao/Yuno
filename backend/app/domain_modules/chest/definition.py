from __future__ import annotations

from typing import Any

from app.domain_modules.chest import services
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

RESOURCE_CAPABILITIES = frozenset(
    {"chest.view", "chest.deposit", "chest.withdraw", "chest.adjust", "chest.history"}
)


def _validate_permissions(data: dict[str, Any], grants: list[Any]) -> list[str]:
    del data
    errors: list[str] = []
    for grant in grants:
        if (
            grant.scope_type == "resource"
            and grant.capability not in RESOURCE_CAPABILITIES
        ):
            errors.append(f"{grant.capability} nao aceita grant por bau.")
        if grant.scope_type == "resource" and not grant.scope_id:
            errors.append("Grant por bau precisa informar scope_id.")
    return errors


class ChestConfigurationParticipant:
    async def validate_draft(
        self, session: Any, *, guild_id: str, instance: Any, draft: Any
    ) -> list[str]:
        del instance
        return await services.validate_catalog_draft(
            session, guild_id=guild_id, draft=draft
        )

    async def materialize_version(
        self, session: Any, *, guild_id: str, instance: Any, draft: Any, version: Any
    ) -> None:
        del instance
        await services.materialize_catalog_version(
            session, guild_id=guild_id, draft=draft, version=version
        )

    async def restore_version(
        self, session: Any, *, guild_id: str, instance: Any, draft: Any, source: Any
    ) -> None:
        del instance
        await services.restore_catalog_version(
            session, guild_id=guild_id, draft=draft, source=source
        )


class ChestHealth:
    key = "chest-domain"

    async def __call__(self, session: Any, guild_id: str) -> list[dict[str, Any]]:
        return await services.diagnostics(session, guild_id=guild_id)


class ChestMigration:
    key = "chest-v1"

    async def inventory(self, session: Any, guild_id: str) -> dict[str, Any]:
        draft = await services.catalog_draft(session, guild_id=guild_id)
        return {
            "draft_chests": len(draft["chests"]),
            "draft_items": len(draft["items"]),
            "legacy_source": False,
        }

    async def validate(self, session: Any, guild_id: str) -> list[str]:
        del session, guild_id
        return []


CHEST_CONFIGURATION = ConfigurationContract(
    schema_version=1,
    fields=(
        ConfigurationField(
            "panel_channel_id",
            "Canal do painel operacional",
            ConfigurationFieldType.channel,
            default="",
        ),
        ConfigurationField(
            "log_channel_id",
            "Canal de logs",
            ConfigurationFieldType.channel,
            default="",
        ),
        ConfigurationField(
            "show_balances_to_members",
            "Exibir saldos aos membros",
            ConfigurationFieldType.boolean,
            default=True,
        ),
        ConfigurationField(
            "allow_personal_history",
            "Permitir historico pessoal",
            ConfigurationFieldType.boolean,
            default=True,
        ),
        ConfigurationField(
            "withdrawal_reason_required",
            "Exigir motivo em retirada",
            ConfigurationFieldType.boolean,
            default=True,
        ),
        ConfigurationField(
            "operator_role_ids",
            "Cargos operadores",
            ConfigurationFieldType.roles,
            default=[],
            constraints={"max_length": 25},
        ),
        ConfigurationField(
            "panel_title",
            "Titulo do painel",
            ConfigurationFieldType.text,
            default="Sistema de Bau",
            constraints={"min_length": 1, "max_length": 80},
        ),
        ConfigurationField(
            "panel_description",
            "Descricao do painel",
            ConfigurationFieldType.text,
            default="Consulte o estoque e registre depositos ou retiradas autorizadas.",
            constraints={"min_length": 1, "max_length": 300},
        ),
    ),
)


MODULE_DEFINITION = ModuleDefinition(
    manifest=ModuleManifest(
        key="chest",
        name="Sistema de Bau",
        description="Catalogo versionado, estoque transacional e ledger imutavel por guild.",
        contract_version=1,
        domain_version="1.0.0",
        minimum_plan="basico",
        required_discord_permissions=(
            "view_channel",
            "send_messages",
            "read_message_history",
        ),
        provided_resources=("chest", "chest_item", "chest_balance", "chest_movement"),
        runtime_modes=("domain",),
        default_runtime_mode="domain",
    ),
    configuration=CHEST_CONFIGURATION,
    capabilities=(
        CapabilityDefinition("chest.configure", administrative=True),
        CapabilityDefinition("chest.view", resource_scoped=True),
        CapabilityDefinition("chest.deposit", resource_scoped=True),
        CapabilityDefinition("chest.withdraw", resource_scoped=True),
        CapabilityDefinition("chest.adjust", administrative=True, resource_scoped=True),
        CapabilityDefinition("chest.history", resource_scoped=True),
        CapabilityDefinition("chest.history_own", allow_resource_owner=True),
        CapabilityDefinition("chest.audit", administrative=True),
        CapabilityDefinition("chest.recover", administrative=True),
        CapabilityDefinition(
            "chest.automation",
            allow_automation=True,
            denial_reason="Somente automacao autorizada.",
        ),
    ),
    lifecycle=LifecyclePolicy(requires_published_configuration=True),
    panels=(PanelContract("chest", recovery_policy="automatic"),),
    actions=(
        ActionContract("view_stock", "chest.view", panel_key="chest"),
        ActionContract("deposit", "chest.deposit", panel_key="chest"),
        ActionContract("withdraw", "chest.withdraw", panel_key="chest"),
        ActionContract("history_own", "chest.history_own", panel_key="chest"),
    ),
    jobs=(JobDefinition("chest.panel.reconcile", max_attempts=5),),
    notifications=(
        NotificationDefinition("chest.panel", ("channel",)),
        NotificationDefinition("chest.log", ("channel",)),
    ),
    health_checks=(ChestHealth(),),
    migration=ChestMigration(),
    permission_validator=_validate_permissions,
    relational_configuration=ChestConfigurationParticipant(),
)
