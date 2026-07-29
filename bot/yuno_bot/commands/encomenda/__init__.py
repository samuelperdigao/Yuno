"""Modulo de Encomendas."""

from yuno_bot.commands.encomenda.cog import EncomendaCog
from yuno_bot.modules import DashboardField, ModuleSpec, SetupChannel

MODULE = ModuleSpec(
    key="encomenda",
    nome="Sistema de Encomenda",
    descricao="Registro de encomendas de produtos pelos membros.",
    icon="\U0001F4E6",
    ordem=50,
    cogs=(lambda ctx: EncomendaCog(ctx.bot),),
    setup_channels=(SetupChannel("encomendas", "encomendas", "operacao", ("encomenda.criar",)),),
    log_channel="logs-encomenda",
    # Sem comando de restricao por cargo hoje -- so o canal criado por
    # `/yuno configurar` (setup_channels abaixo). Ver debito tecnico.
    dashboard_fields=(
        DashboardField("panel_channel_id", "Canal de encomendas", "channel"),
    ),
)
