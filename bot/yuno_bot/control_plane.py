from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import discord
from pydantic import BaseModel


SeedFromLegacy = Callable[[dict[str, Any]], dict[str, Any]]
ValidateConfig = Callable[[dict[str, Any]], tuple[list[str], list[str]]]
EditorHandler = Callable[[discord.Interaction, Any, dict[str, Any], dict[str, Any]], Awaitable[None]]
PreviewHandler = Callable[[discord.Interaction, Any, dict[str, Any], dict[str, Any]], Awaitable[None]]
PublishHandler = Callable[[discord.Interaction, Any, dict[str, Any], dict[str, Any]], Awaitable[None]]
ProjectToLegacy = Callable[[dict[str, Any], dict[str, Any], bool], dict[str, Any]]
DiagnoseHandler = Callable[[discord.Interaction, Any, dict[str, Any], dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class ControlPlaneSpec:
    """Contrato extensivel entre a Central e o Runtime de um modulo."""

    schema_version: int
    config_model: type[BaseModel]
    seed_from_legacy: SeedFromLegacy
    validate: ValidateConfig
    build_editor: EditorHandler
    build_preview: PreviewHandler
    publish_panel: PublishHandler
    project_to_legacy: ProjectToLegacy
    diagnose: DiagnoseHandler


def is_control_plane_admin(
    guild: discord.Guild,
    member: discord.Member,
    config: dict[str, Any],
) -> bool:
    if guild.owner_id == member.id:
        return True
    permissions = member.guild_permissions
    if permissions.administrator or permissions.manage_guild:
        return True
    allowed_roles = {str(role_id) for role_id in config.get("admin_role_ids") or []}
    return bool(allowed_roles.intersection(str(role.id) for role in member.roles))


def pending_changes(state: dict[str, Any]) -> bool:
    return bool(state.get("draft_revision", 0)) and (
        state.get("draft_data") != state.get("published_data")
        or state.get("published_revision", 0) == 0
    )
