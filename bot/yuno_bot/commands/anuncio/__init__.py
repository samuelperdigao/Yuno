"""Modulo de Anuncios."""

from yuno_bot.commands.anuncio.cog import AnuncioCog
from yuno_bot.commands.anuncio.views import AnuncioPanelView
from yuno_bot.modules import DashboardField, ModuleSpec, SetupChannel

MODULE = ModuleSpec(
    key="anuncio",
    nome="Sistema de Anúncio",
    descricao="Publicacao de anuncios com @everyone, restrita a cargos autorizados.",
    icon="📢",
    ordem=100,
    cogs=(lambda ctx: AnuncioCog(ctx.bot),),
    views=(lambda ctx: AnuncioPanelView(ctx.api),),
    setup_channels=(SetupChannel("anuncios", "anuncios", "operacao", ()),),
    log_channel="logs-anuncio",
    dashboard_fields=(
        DashboardField("panel_channel_id", "Canal de anuncios", "channel"),
        DashboardField("role_ids", "Cargos anunciantes", "roles"),
    ),
)
