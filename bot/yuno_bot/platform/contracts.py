from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import discord


@dataclass(frozen=True)
class ActorContext:
    guild_id: int
    user_id: int | None
    role_ids: tuple[int, ...]
    discord_permissions: tuple[str, ...]
    channel_id: int | None
    category_id: int | None
    actor_type: str
    is_guild_owner: bool
    correlation_id: str

    def as_payload(self, *, resource_owner_id: str | None = None) -> dict[str, Any]:
        return {
            "guild_id": str(self.guild_id),
            "user_id": str(self.user_id) if self.user_id is not None else None,
            "role_ids": [str(item) for item in self.role_ids],
            "discord_permissions": list(self.discord_permissions),
            "channel_id": str(self.channel_id) if self.channel_id is not None else None,
            "category_id": str(self.category_id) if self.category_id is not None else None,
            "actor_type": self.actor_type,
            "is_guild_owner": self.is_guild_owner,
            "resource_owner_id": resource_owner_id,
            "correlation_id": self.correlation_id,
        }


@dataclass(frozen=True)
class InteractionResult:
    content: str | None = None
    ephemeral: bool = True
    embed: discord.Embed | None = None
    modal: discord.ui.Modal | None = None
    view: discord.ui.View | None = None
    edit_message: bool = False


@dataclass(frozen=True)
class RoutedContext:
    interaction: discord.Interaction
    actor: ActorContext
    panel: dict[str, Any]
    api: Any
    receipt_id: str


ActionHandler = Callable[[RoutedContext], Awaitable[InteractionResult]]
ResourceOwnerResolver = Callable[[discord.Interaction, dict[str, Any], Any], Awaitable[str | None]]
JobHandler = Callable[[discord.Client, Any, dict[str, Any]], Awaitable[dict[str, Any]]]
DeliveryHandler = Callable[[discord.Client, dict[str, Any]], Awaitable[str | None]]
PanelRenderer = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
AdminPageRenderer = Callable[[discord.Interaction, Any], Awaitable[None]]


@dataclass(frozen=True)
class AdminPageDefinition:
    key: str
    renderer: AdminPageRenderer


@dataclass(frozen=True)
class PanelDefinition:
    key: str
    renderer: PanelRenderer
    version: int = 1
    recovery_policy: str = "manual"


@dataclass(frozen=True)
class ActionDefinition:
    key: str
    surface: str
    capability: str
    handler: ActionHandler
    panel_key: str | None = None
    resource_owner_resolver: ResourceOwnerResolver | None = None


@dataclass(frozen=True)
class JobHandlerDefinition:
    key: str
    handler: JobHandler


@dataclass(frozen=True)
class DeliveryRendererDefinition:
    key: str
    handler: DeliveryHandler


@dataclass(frozen=True)
class ModuleUIAdapter:
    module_key: str
    contract_version: int
    name: str = ""
    description: str = ""
    icon: str = "\u2699\ufe0f"
    order: int = 100
    minimum_plan: str = "basico"
    admin_pages: tuple[AdminPageDefinition, ...] = ()
    panels: tuple[PanelDefinition, ...] = ()
    actions: tuple[ActionDefinition, ...] = ()
    jobs: tuple[JobHandlerDefinition, ...] = ()
    deliveries: tuple[DeliveryRendererDefinition, ...] = ()
