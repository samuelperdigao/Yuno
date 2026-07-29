"""Modulo de Set: solicitacao, aprovacao e reprovacao de entrada de membros."""

from yuno_bot.commands.set.cog import SetCog
from yuno_bot.commands.set.views import SetPanelView
from yuno_bot.modules import DashboardField, ModuleSpec, SetupChannel

MODULE = ModuleSpec(
    key="set",
    nome="Sistema de Set",
    descricao="Solicitacao, aprovacao e reprovacao de set dos membros novos.",
    icon="\U0001F3AE",
    ordem=10,
    cogs=(lambda ctx: SetCog(ctx.bot),),
    views=(lambda ctx: SetPanelView(ctx.api),),
    setup_channels=(
        SetupChannel("set_solicitar", "set-solicitar", "operacao", ("set.solicitar",)),
        SetupChannel("set_aprovacao", "set-aprovacao", "admin", ("set.aprovar", "set.reprovar")),
    ),
    log_channel="logs-set",
    dashboard_fields=(
        DashboardField("panel_channel_id", "Canal de solicitacao", "channel"),
        DashboardField("approval_channel_id", "Canal de aprovacao", "channel"),
        DashboardField("approval_role_id", "Cargo aprovador", "role"),
        DashboardField("approved_role_id", "Cargo dado ao aprovar", "role"),
    ),
)
