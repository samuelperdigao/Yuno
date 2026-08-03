"""Modulo de Parcerias."""

from yuno_bot.commands.parceria.cog import ParceriaCog
from yuno_bot.commands.parceria.views import ParceriaPanelView
from yuno_bot.modules import DashboardField, ModuleSpec, SetupChannel

# As fabricas dependem de `bot.parcerias_repository` (ParceriasRepository),
# que fala HTTP com /internal/parcerias/* no backend -- ver app/parceria.py.
MODULE = ModuleSpec(
    key="parceria",
    nome="Sistema de Parceria",
    descricao="Cadastro, edicao e remocao das parcerias do servidor.",
    icon="\U0001F91D",
    ordem=40,
    cogs=(lambda ctx: ParceriaCog(ctx.bot, ctx.bot.parcerias_repository),),
    views=(lambda ctx: ParceriaPanelView(ctx.api, ctx.bot.parcerias_repository),),
    setup_channels=(SetupChannel("parcerias", "parcerias", "operacao", ("parceria.cadastrar",)),),
    log_channel="logs-parceria",
    dashboard_fields=(
        DashboardField("registrar_channel_id", "Canal do painel de parcerias", "channel"),
        DashboardField("ativas_channel_id", "Canal das parcerias ativas", "channel"),
        DashboardField("category_id", "Categoria das parcerias", "category", obrigatorio=False),
        DashboardField("manager_role_ids", "Cargos gerentes", "roles"),
    ),
)
