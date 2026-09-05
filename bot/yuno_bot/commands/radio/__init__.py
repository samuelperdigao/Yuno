"""Modulo de Radio."""

from yuno_bot.commands.radio.cog import RadioCog
from yuno_bot.commands.radio.views import RadioPanelView
from yuno_bot.modules import DashboardField, ModuleSpec, SetupChannel

MODULE = ModuleSpec(
    key="radio",
    nome="Sistema de Rádio",
    descricao="Painel para anunciar a frequência atual da rádio do servidor.",
    icon="📻",
    ordem=70,
    cogs=(lambda ctx: RadioCog(ctx.bot),),
    views=(lambda ctx: RadioPanelView(ctx.api),),
    setup_channels=(SetupChannel("radio", "radio", "operacao", ()),),
    dashboard_fields=(
        DashboardField("radio", "Canal de rádio", "channel"),
    ),
    retired=False,
)
