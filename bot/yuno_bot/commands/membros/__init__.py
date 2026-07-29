"""Modulo de entrada e saida de membros."""

from yuno_bot.commands.membros.cog import MembrosCog
from yuno_bot.modules import DashboardField, ModuleSpec, SetupChannel

MODULE = ModuleSpec(
    key="membros",
    nome="Entrada e Saída de Membros",
    descricao="Cargo automatico ao entrar, logs de entrada/saida e liberacao da pasta de farm.",
    icon="👥",
    ordem=120,
    cogs=(lambda ctx: MembrosCog(ctx.bot),),
    setup_channels=(
        SetupChannel("membros_entrada", "logs-membros-entrada", "logs", ()),
        SetupChannel("membros_saida", "logs-membros-saida", "logs", ()),
    ),
    dashboard_fields=(DashboardField("welcome_role_id", "Cargo automatico ao entrar", "role", obrigatorio=False),),
)
