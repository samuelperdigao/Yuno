from __future__ import annotations

import re
from typing import Any

import discord
import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from yuno_bot.api_client import ControlPlaneConflict, YunoAPI
from yuno_bot.commands.meta.embeds import (
    build_meta_definition_text,
    meta_panel_embed,
    parse_meta_definition,
)
from yuno_bot.commands.meta.views import MetaPanelView
from yuno_bot.commands.panels import remove_previous_panel
from yuno_bot.control_plane import ControlPlaneSpec, pending_changes


SCHEMA_VERSION = 1
DEFAULT_TITLE = "Metas Semanais"
DEFAULT_DESCRIPTION = "Consulte e defina as metas da organização."
DEFAULT_COLOR = "#FFC72C"
COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")


class MetaItemConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    quantity: int = Field(gt=0)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Informe o nome do item.")
        return normalized


class MetaPanelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default=DEFAULT_TITLE, min_length=1, max_length=256)
    description: str = Field(default=DEFAULT_DESCRIPTION, min_length=1, max_length=4096)
    color: str = DEFAULT_COLOR

    @field_validator("title", "description")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("color")
    @classmethod
    def validate_color(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not COLOR_PATTERN.fullmatch(normalized):
            raise ValueError("Use uma cor hexadecimal no formato #RRGGBB.")
        return normalized


class MetaConfig(BaseModel):
    """Rascunho tipado; campos Discord podem ficar vazios ate a publicacao."""

    model_config = ConfigDict(extra="forbid")

    panel_channel_id: str | None = None
    result_channel_id: str | None = None
    allowed_role_id: str | None = None
    default_items: list[MetaItemConfig] = Field(default_factory=list, max_length=20)
    panel: MetaPanelConfig = Field(default_factory=MetaPanelConfig)

    @field_validator("panel_channel_id", "result_channel_id", "allowed_role_id", mode="before")
    @classmethod
    def normalize_id(cls, value: Any) -> str | None:
        if value in (None, ""):
            return None
        normalized = str(value).strip()
        if not normalized.isdigit():
            raise ValueError("ID do Discord invalido.")
        return normalized

    @model_validator(mode="after")
    def unique_items(self) -> "MetaConfig":
        names = [item.name.casefold() for item in self.default_items]
        if len(names) != len(set(names)):
            raise ValueError("Nao use nomes de itens duplicados.")
        return self


def parse_config(data: dict[str, Any]) -> MetaConfig:
    return MetaConfig.model_validate(data or {})


def seed_from_legacy(config: dict[str, Any]) -> dict[str, Any]:
    settings = (config.get("settings") or {}).get("meta") or {}
    panel = ((config.get("messages") or {}).get("meta") or {}).get("panel") or {}
    permissions = config.get("command_permissions") or {}
    definir_rule = permissions.get("meta.definir") or permissions.get("meta") or {}

    items = settings.get("default_items") or []
    if not items and settings.get("last_definition_text"):
        try:
            items = parse_meta_definition(str(settings["last_definition_text"]))
        except ValueError:
            items = []

    role_ids = definir_rule.get("role_ids") or []
    raw = {
        "panel_channel_id": settings.get("panel_channel_id"),
        "result_channel_id": settings.get("result_channel_id"),
        "allowed_role_id": settings.get("allowed_role_id") or (role_ids[0] if role_ids else None),
        "default_items": items,
        "panel": {
            "title": panel.get("title") or DEFAULT_TITLE,
            "description": panel.get("description") or DEFAULT_DESCRIPTION,
            "color": panel.get("color") or DEFAULT_COLOR,
        },
    }
    try:
        return parse_config(raw).model_dump(mode="json")
    except ValidationError:
        # Importacao legada nunca derruba a Central. Campos invalidos ficam
        # vazios e aparecem no diagnostico para correcao manual. Identidades
        # Discord validas sao preservadas mesmo se outro campo legado estiver
        # corrompido.
        sanitized: dict[str, Any] = MetaConfig().model_dump(mode="json")
        for key in ("panel_channel_id", "result_channel_id", "allowed_role_id"):
            value = raw.get(key)
            if value not in (None, "") and str(value).isdigit():
                sanitized[key] = str(value)
        try:
            sanitized["default_items"] = MetaConfig(default_items=items).model_dump(mode="json")[
                "default_items"
            ]
        except ValidationError:
            pass
        try:
            sanitized["panel"] = MetaPanelConfig.model_validate(raw["panel"]).model_dump(mode="json")
        except ValidationError:
            pass
        return sanitized


def validate(data: dict[str, Any]) -> tuple[list[str], list[str]]:
    try:
        config = parse_config(data)
    except ValidationError as exc:
        return ([error["msg"].removeprefix("Value error, ") for error in exc.errors()], [])

    errors: list[str] = []
    if not config.panel_channel_id:
        errors.append("Selecione o canal do painel.")
    if not config.result_channel_id:
        errors.append("Selecione o canal de resultado.")
    if not config.allowed_role_id:
        errors.append("Selecione o cargo autorizado.")
    if not config.default_items:
        errors.append("Adicione de 1 a 20 itens padrao.")
    return errors, []


def diagnose_state(config: dict[str, Any], state: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors, warnings = validate(state.get("draft_data") or seed_from_legacy(config))
    if int(state.get("schema_version", SCHEMA_VERSION)) != SCHEMA_VERSION:
        errors.insert(0, f"Versao de schema nao suportada; esperado {SCHEMA_VERSION}.")
    if not state.get("published_revision"):
        warnings.append("Nenhuma versao foi publicada pela Central.")
    if pending_changes(state):
        warnings.append("Existem alteracoes de rascunho pendentes de publicacao.")
    return errors, warnings


def project_to_legacy(
    draft_data: dict[str, Any],
    panel_refs: dict[str, Any],
    enabled: bool,
) -> dict[str, Any]:
    config = parse_config(draft_data)
    settings = {
        "panel_channel_id": config.panel_channel_id,
        "result_channel_id": config.result_channel_id,
        "allowed_role_id": config.allowed_role_id,
        "panel_message_id": str(panel_refs["panel_message_id"]),
        "default_items": [item.model_dump() for item in config.default_items],
        "last_definition_text": build_meta_definition_text(
            [item.model_dump() for item in config.default_items]
        ),
    }
    return {
        "settings": settings,
        "messages": config.panel.model_dump(),
        "command_permissions": {
            "meta.definir": {
                "channel_ids": [str(config.panel_channel_id)],
                "role_ids": [str(config.allowed_role_id)],
            }
        },
        "enabled": enabled,
    }


def build_panel_embed(data: dict[str, Any], guild_name: str | None) -> discord.Embed:
    config = parse_config(data)
    embed = meta_panel_embed(guild_name)
    embed.title = config.panel.title
    embed.description = config.panel.description
    embed.color = discord.Color(int(config.panel.color[1:], 16))
    return embed


async def validate_discord(
    guild: discord.Guild,
    data: dict[str, Any],
) -> tuple[list[str], list[str]]:
    errors, warnings = validate(data)
    if errors:
        return errors, warnings
    config = parse_config(data)
    panel_channel = guild.get_channel(int(config.panel_channel_id or 0))
    result_channel = guild.get_channel(int(config.result_channel_id or 0))
    role = guild.get_role(int(config.allowed_role_id or 0))
    if not isinstance(panel_channel, discord.TextChannel):
        errors.append("O canal do painel nao existe ou nao e um canal de texto.")
    if not isinstance(result_channel, discord.TextChannel):
        errors.append("O canal de resultado nao existe ou nao e um canal de texto.")
    if role is None:
        errors.append("O cargo autorizado nao existe mais.")

    bot_member = guild.me
    if bot_member is None:
        errors.append("Nao consegui localizar o usuario do bot no servidor.")
        return errors, warnings
    for label, channel in (("painel", panel_channel), ("resultado", result_channel)):
        if not isinstance(channel, discord.TextChannel):
            continue
        permissions = channel.permissions_for(bot_member)
        if not permissions.view_channel:
            errors.append(f"O bot nao visualiza o canal de {label}.")
        if not permissions.send_messages:
            errors.append(f"O bot nao envia mensagens no canal de {label}.")
        if not permissions.embed_links:
            errors.append(f"O bot nao envia embeds no canal de {label}.")
    if isinstance(result_channel, discord.TextChannel):
        if not result_channel.permissions_for(bot_member).mention_everyone:
            errors.append("O bot nao pode usar a mencao necessaria no canal de resultado.")
    return errors, warnings


async def publish_draft(
    interaction: discord.Interaction,
    api: YunoAPI,
    state: dict[str, Any],
    guild_config: dict[str, Any],
) -> dict[str, Any]:
    if not interaction.guild:
        raise ValueError("Servidor indisponivel.")
    guild = interaction.guild
    draft = state.get("draft_data") or {}
    errors, _ = await validate_discord(guild, draft)
    if errors:
        raise ValueError("\n".join(errors))
    typed = parse_config(draft)
    target = guild.get_channel(int(typed.panel_channel_id or 0))
    if not isinstance(target, discord.TextChannel):
        raise ValueError("Canal do painel invalido.")

    previous = (guild_config.get("settings") or {}).get("meta") or {}
    previous_channel_id = previous.get("panel_channel_id")
    previous_message_id = previous.get("panel_message_id")
    message: discord.Message | None = None
    edited_existing = False
    new_embed = build_panel_embed(draft, guild.name)
    view = MetaPanelView(api)

    if str(previous_channel_id) == str(target.id) and previous_message_id:
        try:
            candidate = await target.fetch_message(int(previous_message_id))
            if guild.me and candidate.author.id != guild.me.id:
                raise ValueError("A mensagem salva do painel nao pertence ao Yuno.")
            await candidate.edit(embed=new_embed, view=view)
            message = candidate
            edited_existing = True
        except discord.NotFound:
            message = None
        except discord.HTTPException as exc:
            raise ValueError("Nao consegui atualizar o painel de Metas.") from exc

    if message is None:
        try:
            message = await target.send(
                embed=new_embed,
                view=view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as exc:
            raise ValueError("Nao consegui publicar o painel de Metas.") from exc

    panel_refs = {"panel_channel_id": str(target.id), "panel_message_id": str(message.id)}
    enabled = bool((guild_config.get("modules") or {}).get("meta", True))
    projection = project_to_legacy(draft, panel_refs, enabled)
    try:
        published = await api.publish_module_config(
            guild.id,
            "meta",
            actor_id=interaction.user.id,
            expected_revision=int(state.get("draft_revision", 0)),
            schema_version=SCHEMA_VERSION,
            projection=projection,
            panel_refs=panel_refs,
        )
    except (httpx.HTTPError, ControlPlaneConflict):
        if edited_existing:
            old_data = state.get("published_data") or seed_from_legacy(guild_config)
            try:
                await message.edit(embed=build_panel_embed(old_data, guild.name), view=view)
            except (ValidationError, discord.HTTPException):
                pass
        else:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
        raise

    await remove_previous_panel(
        guild_config,
        target,
        module_key="meta",
        message_id=message.id,
    )
    return published


def build_spec() -> ControlPlaneSpec:
    from yuno_bot.commands.meta.control_plane_views import (
        show_meta_diagnose,
        show_meta_editor,
        show_meta_preview,
        show_meta_publish,
    )

    return ControlPlaneSpec(
        schema_version=SCHEMA_VERSION,
        config_model=MetaConfig,
        seed_from_legacy=seed_from_legacy,
        validate=validate,
        build_editor=show_meta_editor,
        build_preview=show_meta_preview,
        publish_panel=show_meta_publish,
        project_to_legacy=project_to_legacy,
        diagnose=show_meta_diagnose,
    )
