"""Modulo de moderacao (limpeza de canal, organizacao visual de canais/categorias)."""

from yuno_bot.commands.mod.cog import ModCog
from yuno_bot.modules import ModuleSpec

MODULE = ModuleSpec(
    key="mod",
    nome="Moderação",
    descricao="Limpeza de mensagens e organizacao visual de canais e categorias.",
    icon="🛡️",
    ordem=140,
    cogs=(lambda ctx: ModCog(ctx.bot),),
    dashboard_fields=(),
)
