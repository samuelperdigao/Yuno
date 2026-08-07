"""Infraestrutura compartilhada para paineis fixos dos modulos.

Um painel comercial precisa ter uma unica mensagem por servidor, sobreviver a
restart e manter a regra de canal do comando sincronizada com o lugar onde foi
publicado. Este modulo concentra esse contrato para os cogs nao repetirem a
mesma sequencia de fetch/edit/send/save com pequenas divergencias.
"""

from __future__ import annotations

from collections.abc import Iterable

import discord
import httpx

from yuno_bot.api_client import YunoAPI
from yuno_bot.commands.shared import channel_id_from_setup, resolve_text_channel
from yuno_bot.guards import deny


def customize_panel_embed(embed: discord.Embed, config: dict, module_key: str) -> discord.Embed:
    """Aplica titulo, descricao e cor definidos em ``messages.<modulo>.panel``.

    O formato e propositalmente simples para ser editavel tanto pelo dashboard
    web quanto por qualquer futura interface dentro do Discord.
    """

    module_messages = (config.get("messages") or {}).get(module_key) or {}
    panel = module_messages.get("panel") or {}
    title = str(panel.get("title") or "").strip()
    description = str(panel.get("description") or "").strip()
    color = panel.get("color")

    if title:
        embed.title = title[:256]
    if description:
        embed.description = description[:4096]
    if color not in (None, ""):
        try:
            normalized = str(color).strip().removeprefix("#").removeprefix("0x")
            embed.color = discord.Color(int(normalized, 16))
        except (TypeError, ValueError):
            pass
    return embed


def with_panel_config(
    config: dict,
    *,
    module_key: str,
    channel_id: int,
    message_id: int,
    command_names: Iterable[str] = (),
    role_ids: Iterable[int | str] = (),
) -> dict:
    command_names = tuple(command_names)
    settings = dict(config.get("settings") or {})
    module_settings = dict(settings.get(module_key) or {})
    module_settings["panel_channel_id"] = str(channel_id)
    module_settings["panel_message_id"] = str(message_id)
    normalized_role_ids = [str(role_id) for role_id in role_ids]
    if command_names:
        module_settings["role_ids"] = normalized_role_ids
    settings[module_key] = module_settings

    command_permissions = dict(config.get("command_permissions") or {})
    for command_name in command_names:
        key = f"{module_key}.{command_name}"
        rule = dict(command_permissions.get(key) or {})
        rule["channel_ids"] = [str(channel_id)]
        rule["role_ids"] = normalized_role_ids
        command_permissions[key] = rule

    return {
        "guild_name": config.get("guild_name"),
        "admin_role_ids": config.get("admin_role_ids") or [],
        "log_channel_id": config.get("log_channel_id"),
        "modules": config.get("modules") or {},
        "command_permissions": command_permissions,
        "messages": config.get("messages") or {},
        "settings": settings,
    }


async def publish_or_update_panel(
    channel: discord.TextChannel,
    config: dict,
    *,
    module_key: str,
    embed: discord.Embed,
    view: discord.ui.View,
) -> discord.Message | None:
    """Atualiza a mensagem conhecida ou publica uma unica mensagem nova."""

    module_settings = (config.get("settings") or {}).get(module_key) or {}
    previous_channel_id = module_settings.get("panel_channel_id")
    previous_message_id = module_settings.get("panel_message_id")
    embed = customize_panel_embed(embed, config, module_key)

    if str(previous_channel_id) == str(channel.id) and previous_message_id:
        try:
            message = await channel.fetch_message(int(previous_message_id))
            await message.edit(embed=embed, view=view)
            return message
        except (TypeError, ValueError, discord.HTTPException):
            pass

    try:
        message = await channel.send(
            embed=embed,
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except discord.HTTPException:
        return None

    return message


async def remove_previous_panel(
    config: dict,
    channel: discord.TextChannel,
    *,
    module_key: str,
    message_id: int,
) -> None:
    """Remove o painel antigo somente depois de a nova referencia ser salva."""

    previous = (config.get("settings") or {}).get(module_key) or {}
    previous_channel_id = previous.get("panel_channel_id")
    previous_message_id = previous.get("panel_message_id")
    if not previous_channel_id or not previous_message_id:
        return
    if str(previous_channel_id) == str(channel.id) and str(previous_message_id) == str(message_id):
        return
    try:
        old_channel_id = int(previous_channel_id)
    except (TypeError, ValueError):
        return
    old_channel = channel.guild.get_channel(old_channel_id)
    if not isinstance(old_channel, discord.TextChannel):
        return
    try:
        old_message = await old_channel.fetch_message(int(previous_message_id))
        bot_member = channel.guild.me
        if bot_member and old_message.author.id == bot_member.id:
            await old_message.delete()
    except (TypeError, ValueError, discord.HTTPException):
        pass


async def rollback_unsaved_panel(
    config: dict,
    message: discord.Message,
    *,
    module_key: str,
) -> None:
    """Apaga uma mensagem nova quando a referencia nao pôde ser persistida."""

    previous = (config.get("settings") or {}).get(module_key) or {}
    if (
        str(previous.get("panel_channel_id")) == str(message.channel.id)
        and str(previous.get("panel_message_id")) == str(message.id)
    ):
        return
    try:
        await message.delete()
    except discord.HTTPException:
        pass


async def publish_panel_command(
    interaction: discord.Interaction,
    api: YunoAPI,
    *,
    module_key: str,
    setup_channel_key: str,
    embed: discord.Embed,
    view: discord.ui.View,
    channel: discord.TextChannel | None = None,
    command_names: Iterable[str] = (),
    role_ids: Iterable[int | str] = (),
    label: str,
) -> None:
    """Fluxo completo de ``/<modulo> painel`` para paineis simples."""

    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        await deny(interaction, "use dentro de um servidor.")
        return
    if not (
        interaction.user.guild_permissions.manage_guild
        or interaction.user.guild_permissions.administrator
        or interaction.guild.owner_id == interaction.user.id
    ):
        await deny(interaction, "voce precisa ter permissao de gerenciar servidor.")
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        config = await api.get_guild_config(interaction.guild.id, force=True)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 403:
            await interaction.followup.send("Este servidor ainda nao possui licenca ativa.", ephemeral=True)
            return
        await interaction.followup.send("Nao consegui carregar a configuracao do servidor.", ephemeral=True)
        return
    except httpx.HTTPError:
        await interaction.followup.send("Nao consegui falar com a API do Yuno.", ephemeral=True)
        return

    target = channel
    if target is None:
        configured_id = ((config.get("settings") or {}).get(module_key) or {}).get("panel_channel_id")
        if configured_id:
            target = await resolve_text_channel(interaction.guild, int(configured_id))
    if target is None:
        target = await resolve_text_channel(
            interaction.guild,
            channel_id_from_setup(config, setup_channel_key),
        )
    if target is None:
        await interaction.followup.send(
            "Canal do painel nao encontrado. Rode `/yuno configurar` ou informe um canal no comando.",
            ephemeral=True,
        )
        return

    message = await publish_or_update_panel(
        target,
        config,
        module_key=module_key,
        embed=embed,
        view=view,
    )
    if message is None:
        await interaction.followup.send("Nao consegui publicar o painel no canal informado.", ephemeral=True)
        return

    updated = with_panel_config(
        config,
        module_key=module_key,
        channel_id=target.id,
        message_id=message.id,
        command_names=command_names,
        role_ids=role_ids,
    )
    discord_setup = dict(updated["settings"].get("discord_setup") or {})
    channel_ids = dict(discord_setup.get("channel_ids") or {})
    channel_ids[setup_channel_key] = str(target.id)
    discord_setup["channel_ids"] = channel_ids
    updated["settings"]["discord_setup"] = discord_setup
    try:
        await api.save_guild_config(interaction.guild.id, updated)
    except httpx.HTTPError:
        await rollback_unsaved_panel(config, message, module_key=module_key)
        await interaction.followup.send(
            "Painel publicado, mas nao consegui salvar a configuracao. Tente novamente.",
            ephemeral=True,
        )
        return

    await remove_previous_panel(
        config,
        target,
        module_key=module_key,
        message_id=message.id,
    )

    await interaction.followup.send(f"{label} publicado e fixado em {target.mention}.", ephemeral=True)
