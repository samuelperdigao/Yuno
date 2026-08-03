import discord

from yuno_bot.commands.shared import YUNO_GOLD, YUNO_GREEN, YUNO_ORANGE, YUNO_RED, make_log_embed


def build_set_panel_config(
    current_config: dict,
    *,
    panel_channel_id: int,
    approval_channel_id: int,
    approval_role_id: int,
    approved_role_id: int,
    panel_message_id: int | None = None,
) -> dict:
    command_permissions = dict(current_config.get("command_permissions") or {})

    solicitar_rule = dict(command_permissions.get("set.solicitar") or {})
    solicitar_rule["channel_ids"] = [str(panel_channel_id)]
    command_permissions["set.solicitar"] = solicitar_rule

    for command_key in ("set.aprovar", "set.reprovar"):
        rule = dict(command_permissions.get(command_key) or {})
        rule["channel_ids"] = [str(approval_channel_id)]
        rule["role_ids"] = [str(approval_role_id)]
        command_permissions[command_key] = rule

    settings = dict(current_config.get("settings") or {})
    discord_setup = dict(settings.get("discord_setup") or {})
    channel_ids = dict(discord_setup.get("channel_ids") or {})
    channel_ids["set_solicitar"] = str(panel_channel_id)
    channel_ids["set_aprovacao"] = str(approval_channel_id)
    discord_setup["channel_ids"] = channel_ids
    settings["discord_setup"] = discord_setup

    set_settings = dict(settings.get("set") or {})
    set_settings["approval_channel_id"] = str(approval_channel_id)
    set_settings["approval_role_id"] = str(approval_role_id)
    set_settings["approved_role_id"] = str(approved_role_id)
    set_settings["panel_channel_id"] = str(panel_channel_id)
    if panel_message_id is not None:
        set_settings["panel_message_id"] = str(panel_message_id)
    settings["set"] = set_settings

    return {
        "guild_name": current_config.get("guild_name"),
        "admin_role_ids": current_config.get("admin_role_ids") or [],
        "log_channel_id": current_config.get("log_channel_id"),
        "modules": current_config.get("modules") or {},
        "command_permissions": command_permissions,
        "messages": current_config.get("messages") or {},
        "settings": settings,
    }


def build_set_payload(nome: str, id_fivem: str) -> dict[str, str]:
    nome = nome.strip()[:32]
    id_fivem = id_fivem.strip()
    return {
        "nome": nome,
        "id_fivem": id_fivem,
        "apelido_sugerido": f"{nome} | {id_fivem}",
    }


def panel_embed(guild_name: str | None = None) -> discord.Embed:
    embed = discord.Embed(
        title="🛡️ Painel de Set",
        description="\n".join(
            [
                "📋 **Solicite seu registro no servidor**",
                "",
                "🎮 **ID no Jogo**",
                "Informe apenas numeros, exatamente como aparece na cidade.",
                "",
                "👤 **Nome do Membro**",
                "Use o nome que devera aparecer no seu set.",
                "",
                "✅ **Apos enviar**",
                "Sua solicitacao sera encaminhada para a lideranca aprovar ou reprovar.",
                "",
                "⚠️ **Importante:** Nao saia do servidor durante o processo.",
                "",
                "Clique em **Pedir Set** para iniciar.",
            ]
        ),
        color=YUNO_GOLD,
    )
    embed.set_footer(text="Yuno - Sistema de Registro")
    return embed


def request_embed(interaction: discord.Interaction, record: dict, payload: dict[str, str]) -> discord.Embed:
    embed = discord.Embed(title="Nova Solicitacao de Set", color=YUNO_ORANGE, timestamp=discord.utils.utcnow())
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.add_field(name="ID no Jogo", value=f"`{payload['id_fivem']}`", inline=True)
    embed.add_field(name="Nome", value=payload["nome"], inline=True)
    embed.add_field(name="Solicitante (Discord)", value=f"{interaction.user.mention}\n`{interaction.user.id}`", inline=False)
    embed.set_footer(text=f"Aguardando decisao da lideranca - Protocolo #{record['id']}")
    return embed


def approved_public_embed(interaction: discord.Interaction, record: dict, status_message: str) -> discord.Embed:
    payload = record.get("payload") or {}
    embed = discord.Embed(title="Set Aprovado", color=YUNO_GREEN, timestamp=discord.utils.utcnow())
    embed.set_thumbnail(url=_requester_avatar_url(interaction, record))
    embed.add_field(name="Solicitante", value=f"<@{record['requester_id']}> aprovado por {interaction.user.mention}.", inline=False)
    embed.add_field(name="ID no Jogo", value=f"`{payload.get('id_fivem', 'Nao informado')}`", inline=True)
    embed.add_field(name="Nome", value=payload.get("nome", "Nao informado"), inline=True)
    embed.add_field(name="Resultado", value=status_message, inline=False)
    return embed


def rejected_public_embed(interaction: discord.Interaction, record: dict, motivo: str) -> discord.Embed:
    payload = record.get("payload") or {}
    embed = discord.Embed(title="Set Reprovado", color=YUNO_RED, timestamp=discord.utils.utcnow())
    embed.set_thumbnail(url=_requester_avatar_url(interaction, record))
    embed.add_field(name="Solicitante", value=f"<@{record['requester_id']}> reprovado por {interaction.user.mention}.", inline=False)
    embed.add_field(name="ID no Jogo", value=f"`{payload.get('id_fivem', 'Nao informado')}`", inline=True)
    embed.add_field(name="Nome", value=payload.get("nome", "Nao informado"), inline=True)
    embed.add_field(name="Motivo", value=(motivo or "Nao informado")[:1024], inline=False)
    return embed


def created_log_embed(interaction: discord.Interaction, record: dict, payload: dict[str, str]) -> discord.Embed:
    embed = make_log_embed("Set solicitado", interaction, color=YUNO_ORANGE)
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    embed.add_field(name="Nome", value=payload["nome"], inline=True)
    embed.add_field(name="ID FiveM", value=f"`{payload['id_fivem']}`", inline=True)
    return embed


def approval_log_embed(interaction: discord.Interaction, record: dict, status_message: str) -> discord.Embed:
    embed = make_log_embed("Set aprovado", interaction, color=YUNO_GREEN)
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    embed.add_field(name="Solicitante", value=f"<@{record['requester_id']}>", inline=True)
    embed.add_field(name="Resultado", value=status_message or "Nao informado", inline=False)
    return embed


def rejection_log_embed(interaction: discord.Interaction, record: dict, motivo: str) -> discord.Embed:
    embed = make_log_embed("Set reprovado", interaction, color=YUNO_RED)
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    embed.add_field(name="Solicitante", value=f"<@{record['requester_id']}>", inline=True)
    embed.add_field(name="Motivo", value=motivo[:1024], inline=False)
    return embed


def _requester_avatar_url(interaction: discord.Interaction, record: dict) -> str:
    if str(interaction.user.id) == str(record.get("requester_id")):
        return interaction.user.display_avatar.url
    return interaction.client.user.display_avatar.url if interaction.client.user else interaction.user.display_avatar.url
