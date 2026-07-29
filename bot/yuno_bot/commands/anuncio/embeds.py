import discord

from yuno_bot.commands.shared import YUNO_GOLD, make_log_embed


def build_anuncio_payload(titulo: str, conteudo: str, com_arquivo: bool) -> dict:
    return {"titulo": titulo.strip(), "conteudo": conteudo.strip(), "com_arquivo": com_arquivo}


def anuncio_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📢 Painel de Anúncios",
        description="Clique no botão abaixo para publicar um anúncio neste canal.\n\nApenas cargos autorizados podem publicar.",
        color=YUNO_GOLD,
    )
    embed.set_footer(text="Sistema de Anúncios")
    return embed


def anuncio_post_embed(interaction: discord.Interaction, payload: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"📢 {payload['titulo']}",
        description=payload["conteudo"],
        color=YUNO_GOLD,
        timestamp=discord.utils.utcnow(),
    )
    embed.set_footer(text=f"Anunciado por {interaction.user.display_name}")
    return embed


def anuncio_log_embed(interaction: discord.Interaction, record: dict, payload: dict) -> discord.Embed:
    embed = make_log_embed("Anúncio publicado", interaction, color=YUNO_GOLD)
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    embed.add_field(name="Título", value=payload["titulo"], inline=True)
    embed.add_field(name="Com arquivo", value="Sim" if payload["com_arquivo"] else "Não", inline=True)
    return embed


def build_anuncio_panel_config(
    current_config: dict,
    *,
    panel_channel_id: int,
    role_ids: list[int],
    panel_message_id: int | None = None,
) -> dict:
    command_permissions = dict(current_config.get("command_permissions") or {})
    rule = dict(command_permissions.get("anuncio.publicar") or {})
    rule["role_ids"] = [str(role_id) for role_id in role_ids]
    rule["channel_ids"] = [str(panel_channel_id)]
    command_permissions["anuncio.publicar"] = rule

    settings = dict(current_config.get("settings") or {})
    anuncio_settings = dict(settings.get("anuncio") or {})
    anuncio_settings["panel_channel_id"] = str(panel_channel_id)
    anuncio_settings["role_ids"] = [str(role_id) for role_id in role_ids]
    if panel_message_id is not None:
        anuncio_settings["panel_message_id"] = str(panel_message_id)
    settings["anuncio"] = anuncio_settings

    return {
        "guild_name": current_config.get("guild_name"),
        "admin_role_ids": current_config.get("admin_role_ids") or [],
        "log_channel_id": current_config.get("log_channel_id"),
        "modules": current_config.get("modules") or {},
        "command_permissions": command_permissions,
        "messages": current_config.get("messages") or {},
        "settings": settings,
    }
