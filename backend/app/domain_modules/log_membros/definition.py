from __future__ import annotations

from app.platform.contracts import (
    CapabilityDefinition,
    ConfigurationContract,
    ConfigurationField,
    ConfigurationFieldType,
    LifecyclePolicy,
    ModuleDefinition,
    ModuleManifest,
)

LOG_MEMBROS_CONFIGURATION = ConfigurationContract(
    schema_version=1,
    fields=(
        ConfigurationField(
            "join_channel_id",
            "Canal de log de entrada",
            ConfigurationFieldType.channel,
            required=True,
            description="Canal onde o Yuno publica quando um membro entra no servidor.",
        ),
        ConfigurationField(
            "leave_channel_id",
            "Canal de log de saída",
            ConfigurationFieldType.channel,
            required=True,
            description="Canal onde o Yuno publica quando um membro sai, é expulso ou banido.",
        ),
        ConfigurationField(
            "join_role_ids",
            "Cargos atribuídos na entrada",
            ConfigurationFieldType.roles,
            required=False,
            description=(
                "Cargos atribuídos automaticamente a cada novo membro. "
                "Cada cliente usa cargos diferentes; pode ficar vazio."
            ),
        ),
        ConfigurationField(
            "leave_extra_message",
            "Mensagem extra no log de saída",
            ConfigurationFieldType.text,
            required=False,
            description="Texto livre opcional, anexado ao log de saída.",
            constraints={"max_length": 500},
        ),
    ),
)


MODULE_DEFINITION = ModuleDefinition(
    manifest=ModuleManifest(
        key="log_membros",
        name="Entrada e Saída de Membros",
        description=(
            "Log automático de entrada e saída de membros, com cargo de boas-vindas "
            "configurável e detecção de expulsão/banimento pelo log de auditoria."
        ),
        contract_version=1,
        domain_version="1.0.0",
        required_discord_permissions=(
            "view_channel",
            "send_messages",
            "manage_roles",
            "view_audit_log",
        ),
        provided_resources=(),
        runtime_modes=("domain",),
        default_runtime_mode="domain",
    ),
    configuration=LOG_MEMBROS_CONFIGURATION,
    capabilities=(
        CapabilityDefinition("log_membros.configure", administrative=True, admin_bypass=True),
    ),
    lifecycle=LifecyclePolicy(requires_published_configuration=True),
)
