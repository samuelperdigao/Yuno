import discord

from yuno_bot.commands.shared import make_log_embed

COR_HIERARQUIA = discord.Color.from_rgb(255, 215, 0)

_TIPO_LABEL = {"atribuicao": "ATRIBUIÇÃO", "promocao": "PROMOÇÃO", "rebaixamento": "REBAIXAMENTO", "reatribuicao": "REATRIBUIÇÃO"}
_TIPO_EMOJI = {"atribuicao": "🔄", "promocao": "⬆️", "rebaixamento": "⬇️", "reatribuicao": "🔄"}


def hierarquia_panel_embed(ladder_roles: list[discord.Role]) -> discord.Embed:
    lista = "\n".join(f"`{i + 1}.` {role.mention}" for i, role in enumerate(ladder_roles))
    embed = discord.Embed(
        title="👑 Painel de Hierarquia",
        description=(
            "Gerencie os cargos de hierarquia do servidor.\n\n"
            f"**Cargos (do menor ao maior):**\n{lista}\n\n"
            "Use o botão abaixo para promover ou rebaixar um membro."
        ),
        color=COR_HIERARQUIA,
    )
    embed.set_footer(text="Sistema de Hierarquia")
    return embed


def hierarquia_select_cargo_embed(membro: discord.Member, cargo_atual: discord.Role | None) -> discord.Embed:
    embed = discord.Embed(
        title="👑 Selecione o Novo Cargo",
        description=(
            f"**Membro:** {membro.mention}\n"
            f"**Cargo atual:** {cargo_atual.mention if cargo_atual else '_nenhum_'}\n\n"
            "Escolha o novo cargo de hierarquia:"
        ),
        color=COR_HIERARQUIA,
    )
    embed.set_footer(text="Sistema de Hierarquia")
    return embed


def hierarquia_confirmation_embed(
    membro: discord.Member, cargo_anterior: discord.Role | None, cargo_novo: discord.Role, tipo: str
) -> discord.Embed:
    embed = discord.Embed(title=f"{_TIPO_EMOJI[tipo]} Hierarquia Atualizada", color=COR_HIERARQUIA, timestamp=discord.utils.utcnow())
    embed.add_field(name="Membro", value=membro.mention, inline=True)
    embed.add_field(name="Cargo anterior", value=cargo_anterior.mention if cargo_anterior else "_nenhum_", inline=True)
    embed.add_field(name="Novo cargo", value=cargo_novo.mention, inline=True)
    embed.add_field(name="Tipo", value=f"`{_TIPO_LABEL[tipo]}`", inline=True)
    embed.set_footer(text="Sistema de Hierarquia")
    return embed


def hierarquia_log_embed(
    interaction: discord.Interaction,
    record: dict,
    membro: discord.Member,
    cargo_anterior: discord.Role | None,
    cargo_novo: discord.Role,
    tipo: str,
) -> discord.Embed:
    embed = make_log_embed(f"{_TIPO_EMOJI[tipo]} Hierarquia Atualizada — {_TIPO_LABEL[tipo]}", interaction, color=COR_HIERARQUIA)
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    embed.add_field(name="Membro afetado", value=f"{membro.mention}\n`{membro.id}`", inline=True)
    embed.add_field(name="Cargo anterior", value=cargo_anterior.mention if cargo_anterior else "_nenhum_", inline=True)
    embed.add_field(name="Novo cargo", value=cargo_novo.mention, inline=True)
    return embed


def build_hierarquia_panel_config(
    current_config: dict,
    *,
    panel_channel_id: int,
    ladder_role_ids: list[int],
    manager_role_ids: list[int],
    panel_message_id: int | None = None,
) -> dict:
    command_permissions = dict(current_config.get("command_permissions") or {})
    rule = dict(command_permissions.get("hierarquia.gerenciar") or {})
    rule["role_ids"] = [str(role_id) for role_id in manager_role_ids]
    rule["channel_ids"] = [str(panel_channel_id)]
    command_permissions["hierarquia.gerenciar"] = rule

    settings = dict(current_config.get("settings") or {})
    hierarquia_settings = dict(settings.get("hierarquia") or {})
    hierarquia_settings["panel_channel_id"] = str(panel_channel_id)
    hierarquia_settings["role_ids"] = [str(role_id) for role_id in ladder_role_ids]
    hierarquia_settings["manager_role_ids"] = [str(role_id) for role_id in manager_role_ids]
    if panel_message_id is not None:
        hierarquia_settings["panel_message_id"] = str(panel_message_id)
    settings["hierarquia"] = hierarquia_settings

    return {
        "guild_name": current_config.get("guild_name"),
        "admin_role_ids": current_config.get("admin_role_ids") or [],
        "log_channel_id": current_config.get("log_channel_id"),
        "modules": current_config.get("modules") or {},
        "command_permissions": command_permissions,
        "messages": current_config.get("messages") or {},
        "settings": settings,
    }
