from __future__ import annotations

import json
from typing import Any

import discord

ACTION_ROW = 1
BUTTON = 2
STRING_SELECT = 3
ROLE_SELECT = 6
USER_SELECT = 5
CHANNEL_SELECT = 8
SECTION = 9
TEXT_DISPLAY = 10
THUMBNAIL = 11
MEDIA_GALLERY = 12
SEPARATOR = 14
CONTAINER = 17
LABEL = 18
TEXT_INPUT = 4
MAX_STRING_SELECT_OPTIONS = 25
FLAG_COMPONENTS_V2 = 1 << 15


def text_display(content: str) -> dict[str, Any]:
    return {"type": TEXT_DISPLAY, "content": content}


def thumbnail(url: str, *, description: str | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"type": THUMBNAIL, "media": {"url": url}}
    if description:
        value["description"] = description
    return value


def section(
    *components: dict[str, Any], accessory: dict[str, Any]
) -> dict[str, Any]:
    return {
        "type": SECTION,
        "components": list(components),
        "accessory": accessory,
    }


def separator(*, spacing: int = 1, divider: bool = True) -> dict[str, Any]:
    return {"type": SEPARATOR, "spacing": spacing, "divider": divider}


def button(
    *,
    custom_id: str,
    label: str,
    style: int = 1,
    emoji: str | None = None,
    disabled: bool = False,
) -> dict[str, Any]:
    component: dict[str, Any] = {
        "type": BUTTON,
        "style": style,
        "label": label,
        "custom_id": custom_id,
        "disabled": disabled,
    }
    if emoji:
        component["emoji"] = {"name": emoji}
    return component


def string_select(
    *,
    custom_id: str,
    options: list[dict[str, Any]],
    placeholder: str,
    min_values: int = 1,
    max_values: int = 1,
) -> dict[str, Any]:
    if len(options) > MAX_STRING_SELECT_OPTIONS:
        raise ValueError(
            f"String Select aceita no máximo {MAX_STRING_SELECT_OPTIONS} opções; "
            "pagine a coleção antes de renderizar."
        )
    return {
        "type": STRING_SELECT,
        "custom_id": custom_id,
        "options": list(options),
        "placeholder": placeholder,
        "min_values": min_values,
        "max_values": max_values,
    }


def channel_select(
    *, custom_id: str, placeholder: str, channel_types: list[int] | None = None
) -> dict[str, Any]:
    component: dict[str, Any] = {
        "type": CHANNEL_SELECT,
        "custom_id": custom_id,
        "placeholder": placeholder,
        "min_values": 1,
        "max_values": 1,
    }
    if channel_types:
        component["channel_types"] = channel_types
    return component


def role_select(
    *,
    custom_id: str,
    placeholder: str,
    min_values: int = 1,
    max_values: int = 1,
) -> dict[str, Any]:
    return {
        "type": ROLE_SELECT,
        "custom_id": custom_id,
        "placeholder": placeholder,
        "min_values": min_values,
        "max_values": max_values,
    }


def user_select(
    *, custom_id: str, placeholder: str, min_values: int = 1, max_values: int = 1
) -> dict[str, Any]:
    return {
        "type": USER_SELECT,
        "custom_id": custom_id,
        "placeholder": placeholder,
        "min_values": min_values,
        "max_values": max_values,
    }


def action_row(*components: dict[str, Any]) -> dict[str, Any]:
    return {"type": ACTION_ROW, "components": list(components)}


def media_gallery(urls: list[str] | tuple[str, ...]) -> dict[str, Any]:
    """Build a Discord media gallery without exceeding its ten-item limit."""

    return {
        "type": MEDIA_GALLERY,
        "items": [{"media": {"url": url}} for url in urls[:10]],
    }


def media(url: str) -> dict[str, Any]:
    return media_gallery([url])


def modal_text_input(
    *,
    custom_id: str,
    style: int = 1,
    required: bool = True,
    min_length: int | None = None,
    max_length: int | None = None,
    placeholder: str | None = None,
    value: str | None = None,
) -> dict[str, Any]:
    component: dict[str, Any] = {
        "type": TEXT_INPUT,
        "custom_id": custom_id,
        "style": style,
        "required": required,
    }
    if min_length is not None:
        component["min_length"] = min_length
    if max_length is not None:
        component["max_length"] = max_length
    if placeholder:
        component["placeholder"] = placeholder
    if value is not None:
        component["value"] = value
    return component


def modal_label(
    *,
    label: str,
    component: dict[str, Any],
    description: str | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "type": LABEL,
        "label": label[:45],
        "component": component,
    }
    if description:
        value["description"] = description[:100]
    return value


def modal_payload(
    *, title: str, custom_id: str, labels: list[dict[str, Any]]
) -> dict[str, Any]:
    if not 1 <= len(labels) <= 5:
        raise ValueError("Modal deve conter entre um e cinco campos Label.")
    if any(item.get("type") != LABEL for item in labels):
        raise ValueError("Modal aceita somente componentes Label no primeiro nivel.")
    return {
        "title": title[:45],
        "custom_id": custom_id,
        "components": labels,
    }


def container(
    *components: dict[str, Any],
    accent_color: int | None = None,
    component_id: int | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {"type": CONTAINER, "components": list(components)}
    if accent_color is not None:
        value["accent_color"] = accent_color
    if component_id is not None:
        value["id"] = component_id
    return value


def payload(*components: dict[str, Any]) -> dict[str, Any]:
    return {
        "flags": FLAG_COMPONENTS_V2,
        "components": list(components),
        "allowed_mentions": {"parse": [], "replied_user": False},
    }


def meta_notice_payload(*components: dict[str, Any]) -> dict[str, Any]:
    """Unica superficie que pode interpretar @everyone no Yuno."""

    return {
        "flags": FLAG_COMPONENTS_V2,
        "components": list(components),
        "allowed_mentions": {"parse": ["everyone"], "replied_user": False},
    }


async def send_message(
    bot: discord.Client,
    channel_id: int,
    data: dict[str, Any],
    *,
    files: list[discord.File] | tuple[discord.File, ...] | None = None,
) -> int:
    route = discord.http.Route("POST", "/channels/{channel_id}/messages", channel_id=channel_id)
    response = await _message_request(bot, route, data, files=files)
    return int(response["id"])


async def edit_message(
    bot: discord.Client,
    channel_id: int,
    message_id: int,
    data: dict[str, Any],
    *,
    files: list[discord.File] | tuple[discord.File, ...] | None = None,
) -> None:
    route = discord.http.Route(
        "PATCH",
        "/channels/{channel_id}/messages/{message_id}",
        channel_id=channel_id,
        message_id=message_id,
    )
    await _message_request(bot, route, data, files=files)


async def _message_request(
    bot: discord.Client,
    route: discord.http.Route,
    data: dict[str, Any],
    *,
    files: list[discord.File] | tuple[discord.File, ...] | None = None,
) -> Any:
    """Envia JSON ou multipart mantendo a mesma API de Components V2."""

    body = _restricted(data)
    if not files:
        return await bot.http.request(route, json=body)

    body["attachments"] = [
        file.to_dict(index)
        for index, file in enumerate(files)
    ]
    form = [
        {
            "name": "payload_json",
            "value": json.dumps(body, ensure_ascii=False, separators=(",", ":")),
        }
    ]
    try:
        return await bot.http.request(route, files=list(files), form=form)
    finally:
        for file in files:
            file.close()


async def send_meta_notice(
    bot: discord.Client,
    channel_id: int,
    data: dict[str, Any],
    *,
    nonce: str | int | None = None,
) -> int:
    route = discord.http.Route("POST", "/channels/{channel_id}/messages", channel_id=channel_id)
    body = _meta_restricted(data)
    if nonce is not None:
        body = {**body, "nonce": nonce, "enforce_nonce": True}
    response = await bot.http.request(route, json=body)
    return int(response["id"])


async def edit_meta_notice(
    bot: discord.Client, channel_id: int, message_id: int, data: dict[str, Any]
) -> None:
    route = discord.http.Route(
        "PATCH",
        "/channels/{channel_id}/messages/{message_id}",
        channel_id=channel_id,
        message_id=message_id,
    )
    await bot.http.request(route, json=_meta_restricted(data))


async def edit_interaction_message(
    interaction: discord.Interaction, data: dict[str, Any], *, ephemeral: bool = True
) -> None:
    if not interaction.response.is_done():
        source_is_ephemeral = bool(
            interaction.message is not None and interaction.message.flags.ephemeral
        )
        await interaction.response.defer(
            ephemeral=ephemeral and not source_is_ephemeral,
            thinking=not source_is_ephemeral,
        )
    await edit_webhook_message(
        interaction.client,
        application_id=int(interaction.application_id),
        interaction_token=interaction.token,
        data=data,
    )


async def edit_webhook_message(
    bot: discord.Client,
    *,
    application_id: int,
    interaction_token: str,
    data: dict[str, Any],
) -> None:
    route = discord.http.Route(
        "PATCH",
        "/webhooks/{webhook_id}/{webhook_token}/messages/@original",
        webhook_id=application_id,
        webhook_token=interaction_token,
    )
    await bot.http.request(route, json=_restricted(data))


def _restricted(data: dict[str, Any]) -> dict[str, Any]:
    return {
        **data,
        "allowed_mentions": {"parse": [], "replied_user": False},
    }


def _meta_restricted(data: dict[str, Any]) -> dict[str, Any]:
    return {
        **data,
        "allowed_mentions": {"parse": ["everyone"], "replied_user": False},
    }
