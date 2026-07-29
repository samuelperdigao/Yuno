"""Modulo de Tickets de Farm: acompanhamento semanal individual por ticket."""

from yuno_bot.commands.farm_tickets.cog import FarmTicketsCog
from yuno_bot.commands.farm_tickets.views import FarmPanelView, FarmTicketControlView
from yuno_bot.modules import DashboardField, ModuleSpec

MODULE = ModuleSpec(
    key="farm_tickets",
    nome="Tickets de Farm",
    descricao="Ticket semanal por membro, com lancamento, comprovante e aprovacao.",
    icon="\U0001F3AB",
    ordem=25,
    plano_minimo="pro",
    cogs=(lambda ctx: FarmTicketsCog(ctx.bot),),
    # As views delegam toda a logica ao cog, entao dependem da instancia dele.
    # O loader garante que os cogs sao criados antes das views.
    views=(
        lambda ctx: FarmPanelView(ctx.cog(FarmTicketsCog)),
        lambda ctx: FarmTicketControlView(ctx.cog(FarmTicketsCog)),
    ),
    # Sem canais no setup padrao: o modulo tem configuracao propria
    # (FarmTicketConfig) porque precisa de categorias dedicadas aos tickets.
    setup_channels=(),
    log_channel="logs-farm-tickets",
    dashboard_fields=(
        DashboardField("panel_channel_id", "Canal do painel de farm", "channel"),
        DashboardField("category_ids", "Categorias dos tickets", "category"),
        DashboardField("admin_role_ids", "Cargos administrativos", "roles"),
        DashboardField("participant_role_ids", "Cargos participantes", "roles"),
        DashboardField("folders_category_id", "Categoria das pastas", "category", obrigatorio=False),
    ),
)
