"""Modulo de Acoes."""

from yuno_bot.commands.acao.cog import AcaoCog
from yuno_bot.commands.acao.views import AcaoPainelView, AcaoParticipantesView
from yuno_bot.modules import DashboardField, ModuleSpec, SetupChannel

MODULE = ModuleSpec(
    key="acao",
    nome="Sistema de Ação",
    descricao="Missoes com participantes, resultado e pagamento dividido, catalogo configuravel por servidor.",
    icon="⚡",
    ordem=130,
    plano_minimo="pro",
    cogs=(lambda ctx: AcaoCog(ctx.bot),),
    views=(
        lambda ctx: AcaoPainelView(ctx.api),
        lambda ctx: AcaoParticipantesView(ctx.api),
    ),
    setup_channels=(
        SetupChannel("acao", "acoes", "operacao", ()),
        SetupChannel("acao_ganhas", "logs-acao-ganhas", "logs", ()),
        SetupChannel("acao_perdidas", "logs-acao-perdidas", "logs", ()),
        SetupChannel("acao_pagamento", "logs-acao-pagamento", "logs", ()),
    ),
    dashboard_fields=(
        DashboardField("panel_channel_id", "Canal do painel", "channel"),
        DashboardField("manager_role_ids", "Cargos gerentes", "roles"),
    ),
)
