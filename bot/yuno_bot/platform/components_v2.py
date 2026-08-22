from __future__ import annotations

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
    return {
        "type": STRING_SELECT,
        "custom_id": custom_id,
        "options": options[:25],
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


def media(url: str) -> dict[str, Any]:
    return {"type": MEDIA_GALLERY, "items": [{"media": {"url": url}}]}


def container(*components: dict[str, Any], accent_color: int | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"type": CONTAINER, "components": list(components)}
    if accent_color is not None:
        value["accent_color"] = accent_color
    return value


def payload(*components: dict[str, Any]) -> dict[str, Any]:
    return {
        "flags": FLAG_COMPONENTS_V2,
        "components": list(components),
        "allowed_mentions": {"parse": [], "replied_user": False},
    }


async def send_message(bot: discord.Client, channel_id: int, data: dict[str, Any]) -> int:
    route = discord.http.Route("POST", "/channels/{channel_id}/messages", channel_id=channel_id)
    response = await bot.http.request(route, json=_restricted(data))
    return int(response["id"])


async def edit_message(
    bot: discord.Client, channel_id: int, message_id: int, data: dict[str, Any]
) -> None:
    route = discord.http.Route(
        "PATCH",
        "/channels/{channel_id}/messages/{message_id}",
        channel_id=channel_id,
        message_id=message_id,
    )
    await bot.http.request(route, json=_restricted(data))


def _restricted(data: dict[str, Any]) -> dict[str, Any]:
    return {
        **data,
        "allowed_mentions": {"parse": [], "replied_user": False},
    }
