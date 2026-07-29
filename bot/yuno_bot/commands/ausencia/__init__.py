"""Modulo de Ausencias."""

from yuno_bot.commands.ausencia.cog import AusenciaCog
from yuno_bot.commands.ausencia.views import AusenciaPanelView
from yuno_bot.modules import DashboardField, ModuleSpec, SetupChannel

MODULE = ModuleSpec(
    key="ausencia",
    nome="Sistema de Ausencia",
    descricao="Registro e acompanhamento das ausencias dos membros.",
    icon="\U0001F3D6",
    ordem=60,
    cogs=(lambda ctx: AusenciaCog(ctx.bot),),
    views=(lambda ctx: AusenciaPanelView(ctx.api),),
    setup_channels=(SetupChannel("ausencias", "ausencias", "operacao", ()),),
    log_channel="logs-ausencia",
    dashboard_fields=(
        DashboardField("canal_ausencias_id", "Canal de ausencias", "channel"),
    ),
)
