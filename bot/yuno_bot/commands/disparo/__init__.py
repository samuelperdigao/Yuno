"""Modulo de Disparo de mensagens em massa para pastas de membro."""

from yuno_bot.commands.disparo.cog import DisparoCog
from yuno_bot.commands.disparo.views import DisparoPanelView
from yuno_bot.modules import DashboardField, ModuleSpec, SetupChannel

MODULE = ModuleSpec(
    key="disparo",
    nome="Disparo de Mensagens",
    descricao="Envio e exclusao de mensagens em massa para as pastas privadas dos membros (requer farm_tickets configurado).",
    icon="📨",
    ordem=150,
    plano_minimo="pro",
    cogs=(lambda ctx: DisparoCog(ctx.bot),),
    views=(lambda ctx: DisparoPanelView(ctx.api),),
    setup_channels=(SetupChannel("disparo", "central-de-disparo", "admin", ()),),
    log_channel=None,
    dashboard_fields=(DashboardField("panel_channel_id", "Canal do painel de disparo", "channel"),),
)
