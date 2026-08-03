"""Modulo de Producao."""

from yuno_bot.commands.producao.cog import ProducaoCog
from yuno_bot.commands.producao.views import ProducaoPanelView
from yuno_bot.modules import DashboardField, ModuleSpec, SetupChannel

MODULE = ModuleSpec(
    key="producao",
    nome="Sistema de Producao",
    descricao="Registro da producao de itens pelos membros.",
    icon="\U0001F3ED",
    ordem=80,
    cogs=(lambda ctx: ProducaoCog(ctx.bot),),
    views=(lambda ctx: ProducaoPanelView(ctx.api),),
    setup_channels=(SetupChannel("producao", "producao", "operacao", ("producao.registrar",)),),
    log_channel="logs-producao",
    dashboard_fields=(
        DashboardField("panel_channel_id", "Canal de producao", "channel"),
        DashboardField("role_ids", "Cargo autorizado", "roles", obrigatorio=False),
    ),
)
