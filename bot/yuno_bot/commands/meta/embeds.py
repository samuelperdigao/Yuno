import discord

from yuno_bot.commands.shared import YUNO_BLUE, YUNO_GOLD, make_log_embed, parse_positive_int


def build_meta_payload(produto: str, quantidade: int, observacao: str) -> dict:
    return {"produto": produto.strip(), "quantidade": quantidade, "observacao": observacao.strip() or "Nao informado"}


def parse_meta_definition(raw_definition: str, *, max_items: int = 20) -> list[dict]:
    items: list[dict] = []
    for line_number, line in enumerate(raw_definition.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        if "," not in line:
            raise ValueError(f"Linha {line_number}: use o formato item, quantidade.")
        name, quantity_text = [part.strip() for part in line.rsplit(",", 1)]
        if not name:
            raise ValueError(f"Linha {line_number}: informe o item.")
        if len(name) > 80:
            raise ValueError(f"Linha {line_number}: item deve ter no maximo 80 caracteres.")
        try:
            quantity = parse_positive_int(quantity_text, "Quantidade")
        except ValueError as exc:
            raise ValueError(f"Linha {line_number}: {exc}") from exc
        items.append({"name": name, "quantity": quantity})

    if not items:
        raise ValueError("Informe pelo menos um item no formato item, quantidade.")
    if len(items) > max_items:
        raise ValueError(f"Informe no maximo {max_items} itens por meta.")
    return items


def build_meta_panel_config(
    current_config: dict,
    *,
    panel_channel_id: int,
    result_channel_id: int,
    allowed_role_id: int,
    panel_message_id: int | None = None,
    last_definition_text: str | None = None,
) -> dict:
    command_permissions = dict(current_config.get("command_permissions") or {})
    definir_rule = dict(command_permissions.get("meta.definir") or {})
    definir_rule["channel_ids"] = [str(panel_channel_id)]
    definir_rule["role_ids"] = [str(allowed_role_id)]
    command_permissions["meta.definir"] = definir_rule

    settings = dict(current_config.get("settings") or {})
    meta_settings = dict(settings.get("meta") or {})
    meta_settings["panel_channel_id"] = str(panel_channel_id)
    meta_settings["result_channel_id"] = str(result_channel_id)
    meta_settings["allowed_role_id"] = str(allowed_role_id)
    if panel_message_id is not None:
        meta_settings["panel_message_id"] = str(panel_message_id)
    if last_definition_text is not None:
        meta_settings["last_definition_text"] = last_definition_text
    settings["meta"] = meta_settings

    return {
        "guild_name": current_config.get("guild_name"),
        "admin_role_ids": current_config.get("admin_role_ids") or [],
        "log_channel_id": current_config.get("log_channel_id"),
        "modules": current_config.get("modules") or {},
        "command_permissions": command_permissions,
        "messages": current_config.get("messages") or {},
        "settings": settings,
    }


def meta_panel_embed(guild_name: str | None = None) -> discord.Embed:
    title = "Painel de Metas"
    description = "\n".join(
        [
            "**Defina os itens e quantidades da meta**",
            "",
            "Use o botao abaixo para abrir o formulario de metas.",
            "No formulario, informe um item por linha no formato:",
            "`item, quantidade`",
            "`item, quantidade`",
            "",
            "A ultima definicao salva neste servidor aparecera preenchida para facilitar edicoes.",
        ]
    )
    embed = discord.Embed(title=title, description=description, color=YUNO_GOLD)
    embed.set_footer(text=f"Yuno - Metas{f' | {guild_name}' if guild_name else ''}")
    return embed


def meta_definition_embed(interaction: discord.Interaction, record: dict, items: list[dict]) -> discord.Embed:
    embed = discord.Embed(title="Meta definida", color=YUNO_BLUE, timestamp=discord.utils.utcnow())
    embed.add_field(name="Responsavel", value=f"{interaction.user.mention}\n`{interaction.user.id}`", inline=True)
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    item_lines = [f"**{index}. {item['name']}** - `{item['quantity']}`" for index, item in enumerate(items, start=1)]
    embed.add_field(name="Itens", value="\n".join(item_lines)[:1024], inline=False)
    embed.set_footer(text="Yuno - Definicao de metas")
    return embed


def meta_log_embed(interaction: discord.Interaction, record: dict, payload: dict) -> discord.Embed:
    embed = make_log_embed("Meta registrada", interaction, color=YUNO_BLUE)
    embed.add_field(name="Protocolo", value=f"#{record['id']}", inline=True)
    embed.add_field(name="Produto", value=payload["produto"], inline=True)
    embed.add_field(name="Quantidade", value=f"`{payload['quantidade']}`", inline=True)
    embed.add_field(name="Observacao", value=payload["observacao"][:1024], inline=False)
    return embed
