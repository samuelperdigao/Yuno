"""Modulo de Disparo de mensagens em massa para os canais privados dos membros."""

from yuno_bot.commands.disparo.cog import DisparoCog
from yuno_bot.commands.disparo.views import DisparoPanelView
from yuno_bot.modules import DashboardField, ModuleSpec, SetupChannel

MODULE = ModuleSpec(
    key="disparo",
    nome="Disparo de Mensagens",
    descricao="Envio e exclusão de mensagens em massa para os canais privados dos membros.",
    icon="📨",
    ordem=150,
    plano_minimo="pro",
    retired=False,
    cogs=(lambda ctx: DisparoCog(ctx.bot),),
    views=(lambda ctx: DisparoPanelView(ctx.api),),
    setup_channels=(SetupChannel("disparo", "central-de-disparo", "admin", ()),),
    log_channel="disparo-logs",
    dashboard_fields=(
        DashboardField(
            "target_category_id",
            "Categoria com os canais privados dos membros",
            "category",
        ),
        DashboardField(
            "excluded_channel_ids",
            "Canais a excluir do disparo",
            "text",
            obrigatorio=False,
            descricao="IDs de canal separados por vírgula. Use para canais reservados (avisos, tutoriais, painéis).",
        ),
    ),
)
