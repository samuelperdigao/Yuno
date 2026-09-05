from __future__ import annotations

from dataclasses import dataclass

import discord

from yuno_bot.platform import ui_kit as uk

ANNOUNCEMENT_COLOR = uk.BRAND
LOG_COLOR = uk.BRAND


def _clip(value: object, *, limit: int) -> str:
    text = str(value or "").strip()
    return text[:limit]


def build_announcement_embed(*, titulo: str, conteudo: str) -> discord.Embed:
    """Embed publicado no canal de anúncios. Título e conteúdo já vêm validados."""
    return discord.Embed(
        title=_clip(titulo, limit=256),
        description=_clip(conteudo, limit=4000),
        color=ANNOUNCEMENT_COLOR,
    )


@dataclass(frozen=True, slots=True)
class AnuncioLogData:
    autor_id: str | None = None
    titulo: str = ""
    canal_id: str | None = None
    mencionou_everyone: bool = False
    quantidade_arquivos: int = 0
    log_title: str = "Novo anúncio publicado"


def build_log_embed(data: AnuncioLogData) -> discord.Embed:
    embed = discord.Embed(title=_clip(data.log_title, limit=256) or "Novo anúncio publicado", color=LOG_COLOR)
    autor = f"<@{data.autor_id}>" if data.autor_id else "—"
    embed.add_field(name="👤 Publicado por", value=autor, inline=True)
    canal = f"<#{data.canal_id}>" if data.canal_id else "—"
    embed.add_field(name="📍 Canal", value=canal, inline=True)
    embed.add_field(name="📝 Título", value=_clip(data.titulo, limit=256) or "—", inline=False)
    embed.add_field(
        name="📣 Mencionou @everyone",
        value="Sim" if data.mencionou_everyone else "Não",
        inline=True,
    )
    embed.add_field(
        name="📎 Arquivos anexados",
        value=str(data.quantidade_arquivos),
        inline=True,
    )
    return embed
