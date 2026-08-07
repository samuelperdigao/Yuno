"""Modulo de Metas semanais."""

from yuno_bot.commands.meta.cog import MetaCog
from yuno_bot.commands.meta.control_plane import build_spec
from yuno_bot.commands.meta.views import MetaPanelView
from yuno_bot.modules import DashboardField, ModuleSpec, SetupChannel

MODULE = ModuleSpec(
    key="meta",
    nome="Sistema de Meta",
    descricao="Definicao e registro das metas semanais do servidor.",
    icon="\U0001F3AF",
    ordem=20,
    cogs=(lambda ctx: MetaCog(ctx.bot),),
    views=(lambda ctx: MetaPanelView(ctx.api),),
    setup_channels=(SetupChannel("metas", "metas-semanais", "operacao", ("meta.registrar",)),),
    log_channel="logs-meta",
    dashboard_fields=(
        DashboardField("panel_channel_id", "Canal do painel de metas", "channel"),
        DashboardField("allowed_role_id", "Cargo que define meta", "role"),
    ),
    control_plane=build_spec(),
)
