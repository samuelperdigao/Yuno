from datetime import datetime, timezone
from typing import Any

import discord


AUSENCIA_GOLD = discord.Color(0xF0A500)
FOOTER_TEXT = "Sistema de Ausências • Yuno"
LOG_FOOTER_TEXT = "Yuno • Sistema de Ausência"


def parse_dias(value: str) -> int:
    normalized = value.strip()
    if not normalized.isdigit():
        raise ValueError("❌ Digite apenas o número de dias.")
    dias = int(normalized)
    if dias < 1:
        raise ValueError("❌ O número de dias precisa ser pelo menos 1.")
    if dias > 7:
        raise ValueError("❌ Ausências acima de 7 dias precisam ser tratadas diretamente com a administração.")
    return dias


def normalize_motivo(value: str | None) -> str:
    motivo = (value or "").strip()
    return motivo[:300] if motivo else "Não informado"


def parse_iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_date_br(value: datetime | str) -> str:
    parsed = parse_iso_datetime(value) if isinstance(value, str) else value
    return parsed.astimezone(timezone.utc).strftime("%d/%m/%Y")


def dias_restantes(fim: datetime | str, now: datetime | None = None) -> int:
    parsed_fim = parse_iso_datetime(fim) if isinstance(fim, str) else fim
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return max((parsed_fim.astimezone(timezone.utc) - current.astimezone(timezone.utc)).days + 1, 0)


def build_ausencia_setup_config(current_config: dict[str, Any], *, channel_id: int) -> dict[str, Any]:
    settings = dict(current_config.get("settings") or {})
    ausencia_settings = dict(settings.get("ausencia") or {})
    ausencia_settings["canal_ausencias_id"] = str(channel_id)
    ausencia_settings["panel_channel_id"] = str(channel_id)
    settings["ausencia"] = ausencia_settings

    discord_setup = dict(settings.get("discord_setup") or {})
    channel_ids = dict(discord_setup.get("channel_ids") or {})
    channel_ids["ausencias"] = str(channel_id)
    discord_setup["channel_ids"] = channel_ids
    settings["discord_setup"] = discord_setup

    return {
        "guild_name": current_config.get("guild_name"),
        "admin_role_ids": current_config.get("admin_role_ids") or [],
        "log_channel_id": current_config.get("log_channel_id"),
        "modules": current_config.get("modules") or {},
        "command_permissions": current_config.get("command_permissions") or {},
        "messages": current_config.get("messages") or {},
        "settings": settings,
    }


def ausencia_channel_id(config: dict[str, Any]) -> int | None:
    settings = config.get("settings") or {}
    channel_id = ((settings.get("ausencia") or {}).get("canal_ausencias_id")) or (
        ((settings.get("discord_setup") or {}).get("channel_ids") or {}).get("ausencias")
    )
    if not channel_id:
        return None
    try:
        return int(channel_id)
    except (TypeError, ValueError):
        return None


def panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🏖️ Sistema de Ausência",
        description=(
            "Vai ficar fora por um tempo?\n\n"
            "Clique no botão abaixo para registrar sua ausência.\n\n"
            "📌 Regras:\n"
            "• Ausências de até 3 dias: registre e fique tranquilo\n"
            "• Ausências de 3 a 7 dias: registre com atenção ao prazo\n"
            "• Mais de 7 dias sem aviso pode gerar penalidade automática\n\n"
            "Sempre renove seu aviso se precisar de mais tempo."
        ),
        color=AUSENCIA_GOLD,
    )
    embed.set_footer(text=FOOTER_TEXT)
    return embed


def ausencia_public_embed(user: discord.User | discord.Member, ausencia: dict[str, Any]) -> discord.Embed:
    dias = int(ausencia["dias"])
    motivo = normalize_motivo(ausencia.get("motivo"))
    embed = discord.Embed(
        title="🏖️ Registro de Ausência",
        description=f"**{user.display_name}** estará ausente por **{dias} dia(s)**.",
        color=AUSENCIA_GOLD,
        timestamp=discord.utils.utcnow(),
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="👤 Membro", value=user.mention, inline=True)
    embed.add_field(name="📅 Dias fora", value=f"{dias} dia(s)", inline=True)
    embed.add_field(name="🔙 Retorno", value=format_date_br(ausencia["fim"]), inline=True)
    embed.add_field(name="📝 Motivo", value=motivo[:1024], inline=False)
    if dias > 3:
        embed.add_field(
            name="⚠️ Atenção",
            value="⚠️ Atenção: você está no limite. Se precisar de mais tempo, renove sua ausência antes do prazo.",
            inline=False,
        )
    embed.set_footer(text=FOOTER_TEXT)
    return embed


def ausencia_log_embed(user: discord.User | discord.Member, ausencia: dict[str, Any]) -> discord.Embed:
    embed = discord.Embed(title="🏖️ Ausência Registrada", color=AUSENCIA_GOLD, timestamp=discord.utils.utcnow())
    embed.add_field(name="👤 Membro", value=f"{user.mention}\n`{user.id}`", inline=True)
    embed.add_field(name="📅 Dias", value=str(ausencia["dias"]), inline=True)
    embed.add_field(name="🔙 Retorno", value=format_date_br(ausencia["fim"]), inline=True)
    embed.add_field(name="📝 Motivo", value=normalize_motivo(ausencia.get("motivo"))[:1024], inline=False)
    embed.set_footer(text=LOG_FOOTER_TEXT)
    return embed


def ausencias_list_embed(ausencias: list[dict[str, Any]]) -> discord.Embed:
    embed = discord.Embed(title="📋 Membros em Ausência", color=AUSENCIA_GOLD, timestamp=discord.utils.utcnow())
    now = datetime.now(timezone.utc)
    for ausencia in ausencias:
        nome = ausencia.get("nome") or f"ID {ausencia['user_id']}"
        embed.add_field(
            name=f"👤 {nome}",
            value=(
                f"Retorno: {format_date_br(ausencia['fim'])}\n"
                f"Dias restantes: {dias_restantes(ausencia['fim'], now)}\n"
                f"Motivo: {normalize_motivo(ausencia.get('motivo'))}"
            ),
            inline=False,
        )
    embed.set_footer(text=FOOTER_TEXT)
    return embed
