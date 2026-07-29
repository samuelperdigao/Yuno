"""Modulo de Radio."""

from yuno_bot.commands.radio.cog import RadioCog
from yuno_bot.commands.radio.views import RadioPainelView
from yuno_bot.modules import DashboardField, ModuleSpec, SetupChannel

MODULE = ModuleSpec(
    key="radio",
    nome="Sistema de Radio",
    descricao="Alteracao e divulgacao da frequencia de radio do servidor.",
    icon="\U0001F4FB",
    ordem=70,
    cogs=(lambda ctx: RadioCog(ctx.bot),),
    views=(lambda ctx: RadioPainelView(ctx.api),),
    setup_channels=(SetupChannel("radio", "radio", "operacao", ("radio.alterar",)),),
    log_channel="logs-radio",
    dashboard_fields=(
        DashboardField("panel_channel_id", "Canal do painel de radio", "channel"),
        DashboardField("manager_role_ids", "Cargos que alteram radio", "roles", obrigatorio=False),
    ),
)
