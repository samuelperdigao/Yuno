"""Modulo de Advertencias."""

from yuno_bot.commands.adv.cog import AdvCog
from yuno_bot.commands.adv.views import AdvPanelView
from yuno_bot.modules import DashboardField, ModuleSpec, SetupChannel

MODULE = ModuleSpec(
    key="adv",
    nome="Sistema de Advertência",
    descricao="Registro de advertencias aplicadas a membros do servidor.",
    icon="⚠️",
    ordem=90,
    cogs=(lambda ctx: AdvCog(ctx.bot),),
    views=(lambda ctx: AdvPanelView(ctx.api),),
    setup_channels=(SetupChannel("adv", "advertencias", "operacao", ("adv.aplicar",)),),
    log_channel="logs-adv",
    dashboard_fields=(DashboardField("panel_channel_id", "Canal de advertencias", "channel"),),
)
