"""Modulo de Tickets de atendimento."""

from yuno_bot.commands.ticket.cog import TicketCog
from yuno_bot.commands.ticket.views import TicketPanelView
from yuno_bot.modules import DashboardField, ModuleSpec, SetupChannel

MODULE = ModuleSpec(
    key="ticket",
    nome="Sistema de Ticket",
    descricao="Abertura de tickets de atendimento pelos membros.",
    icon="\U0001F4E8",
    ordem=30,
    cogs=(lambda ctx: TicketCog(ctx.bot),),
    views=(lambda ctx: TicketPanelView(ctx.api),),
    setup_channels=(SetupChannel("tickets", "tickets", "operacao", ("ticket.abrir",)),),
    log_channel="logs-ticket",
    dashboard_fields=(
        DashboardField("panel_channel_id", "Canal de tickets", "channel"),
        DashboardField("role_ids", "Cargo autorizado", "roles", obrigatorio=False),
    ),
)
