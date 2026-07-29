"""Modulo de Hierarquia de cargos."""

from yuno_bot.commands.hierarquia.cog import HierarquiaCog
from yuno_bot.commands.hierarquia.views import HierarquiaPanelView
from yuno_bot.modules import DashboardField, ModuleSpec, SetupChannel

MODULE = ModuleSpec(
    key="hierarquia",
    nome="Sistema de Hierarquia",
    descricao="Promocao e rebaixamento de membros numa escada de cargos configuravel.",
    icon="👑",
    ordem=110,
    cogs=(lambda ctx: HierarquiaCog(ctx.bot),),
    views=(lambda ctx: HierarquiaPanelView(ctx.api),),
    setup_channels=(SetupChannel("hierarquia", "hierarquia", "admin", ()),),
    log_channel="logs-hierarquia",
    dashboard_fields=(
        DashboardField("panel_channel_id", "Canal do painel", "channel"),
        DashboardField("role_ids", "Escada de cargos (menor ao maior)", "roles"),
        DashboardField("manager_role_ids", "Cargos que podem gerenciar", "roles"),
    ),
)
