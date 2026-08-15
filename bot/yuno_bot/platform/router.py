from __future__ import annotations

import re
from uuid import uuid4

import discord

from yuno_bot.platform.contracts import ActorContext, InteractionResult, RoutedContext
from yuno_bot.platform.registry import UIRegistry, ui_registry


CUSTOM_ID_PATTERN = re.compile(
    r"^yuno:v(?P<version>\d+):(?P<module>[a-z0-9_]{1,32}):"
    r"(?P<surface>[a-z0-9_]{1,32}):(?P<action>[a-z0-9_]{1,32})$"
)


def custom_id(module_key: str, surface: str, action: str, *, version: int = 1) -> str:
    value = f"yuno:v{version}:{module_key}:{surface}:{action}"
    if len(value) > 100 or CUSTOM_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("custom_id invalido para o Interaction Router.")
    return value


def parse_custom_id(value: str) -> dict[str, str | int] | None:
    match = CUSTOM_ID_PATTERN.fullmatch(value)
    if match is None:
        return None
    return {
        "version": int(match.group("version")),
        "module": match.group("module"),
        "surface": match.group("surface"),
        "action": match.group("action"),
    }


class InteractionRouter:
    def __init__(self, api, registry: UIRegistry | None = None) -> None:
        self.api = api
        self.registry = registry or ui_registry

    async def dispatch(
        self,
        interaction: discord.Interaction,
        *,
        module_key: str,
        surface: str,
        action_key: str,
        panel_override: dict | None = None,
    ) -> None:
        if interaction.guild is None or (interaction.message is None and panel_override is None):
            await self._deny(interaction, "Esta acao exige um painel publicado em um servidor.")
            return
        action = self.registry.action(module_key, surface, action_key)
        if action is None:
            await self._deny(interaction, "Acao indisponivel ou contrato incompatível.")
            return
        if action.panel_key and surface != action.panel_key:
            await self._deny(interaction, "A acao nao pertence a este painel.")
            return

        correlation_id = str(interaction.id or uuid4())
        if panel_override is not None:
            panel = panel_override
        else:
            try:
                panel = await self.api.panel_by_message(
                    interaction.guild.id, interaction.channel_id, interaction.message.id
                )
            except Exception:
                await self._deny(interaction, "Nao consegui validar a identidade deste painel.")
                return
        if panel.get("module_key") != module_key or panel.get("panel_key") != surface:
            await self._deny(interaction, "Este painel nao pertence ao recurso solicitado.")
            return

        actor = self._actor_context(interaction, correlation_id)
        try:
            resource_owner_id = None
            if action.resource_owner_resolver is not None:
                resource_owner_id = await action.resource_owner_resolver(
                    interaction, panel, self.api
                )
            permission = await self.api.authorize(
                interaction.guild.id,
                module_key,
                {
                    "capability": action.capability,
                    "actor": actor.as_payload(resource_owner_id=resource_owner_id),
                    "resource_type": panel.get("resource_type", ""),
                    "resource_id": panel.get("resource_id", ""),
                },
            )
        except Exception:
            await self._deny(interaction, "Nao consegui revalidar sua permissao.")
            return
        if not permission.get("allowed"):
            await self._deny(interaction, permission.get("reason") or "Acao nao autorizada.")
            return

        try:
            receipt = await self.api.begin_interaction(
                interaction.guild.id,
                {
                    "interaction_id": str(interaction.id),
                    "module_key": module_key,
                    "action_key": action_key,
                    "resource_type": panel.get("resource_type", ""),
                    "resource_id": panel.get("resource_id", ""),
                    "correlation_id": correlation_id,
                },
            )
        except Exception:
            await self._deny(interaction, "Nao consegui iniciar a acao com seguranca.")
            return
        if receipt.get("duplicate"):
            await self._deny(interaction, "Esta interacao ja foi processada.")
            return

        context = RoutedContext(
            interaction=interaction,
            actor=actor,
            panel=panel,
            api=self.api,
            receipt_id=receipt["receipt_id"],
        )
        try:
            result = await action.handler(context)
            await self._render(interaction, result)
            await self.api.finish_interaction(
                interaction.guild.id,
                receipt["receipt_id"],
                result={"delivered": True, "edit_message": result.edit_message},
            )
        except Exception:
            await self.api.finish_interaction(
                interaction.guild.id,
                receipt["receipt_id"],
                result={},
                error="Falha no handler do modulo.",
            )
            await self._deny(interaction, "Nao consegui concluir a acao. Tente novamente.")

    @staticmethod
    def _actor_context(interaction: discord.Interaction, correlation_id: str) -> ActorContext:
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        permissions: tuple[str, ...] = ()
        role_ids: tuple[int, ...] = ()
        if member is not None:
            permissions = tuple(name for name, enabled in member.guild_permissions if enabled)
            role_ids = tuple(role.id for role in member.roles)
        channel = interaction.channel
        category_id = getattr(channel, "category_id", None)
        return ActorContext(
            guild_id=interaction.guild.id,
            user_id=interaction.user.id if interaction.user else None,
            role_ids=role_ids,
            discord_permissions=permissions,
            channel_id=interaction.channel_id,
            category_id=category_id,
            actor_type="user",
            is_guild_owner=interaction.guild.owner_id == getattr(interaction.user, "id", None),
            correlation_id=correlation_id,
        )

    @staticmethod
    async def _render(interaction: discord.Interaction, result: InteractionResult) -> None:
        if result.modal is not None:
            if interaction.response.is_done():
                raise RuntimeError("Modal nao pode ser aberto depois de responder/deferir.")
            await interaction.response.send_modal(result.modal)
            return
        kwargs = {"content": result.content, "embed": result.embed, "view": result.view}
        if result.edit_message:
            if interaction.response.is_done():
                await interaction.edit_original_response(**kwargs)
            else:
                await interaction.response.edit_message(**kwargs)
            return
        if interaction.response.is_done():
            await interaction.followup.send(**kwargs, ephemeral=result.ephemeral)
        else:
            await interaction.response.send_message(**kwargs, ephemeral=result.ephemeral)

    @staticmethod
    async def _deny(interaction: discord.Interaction, message: str) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


class RoutedActionButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=CUSTOM_ID_PATTERN,
):
    def __init__(
        self,
        item: discord.ui.Button,
        *,
        version: int,
        module_key: str,
        surface: str,
        action_key: str,
    ) -> None:
        super().__init__(item)
        self.version = version
        self.module_key = module_key
        self.surface = surface
        self.action_key = action_key

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "RoutedActionButton":
        del interaction
        return cls(
            item,
            version=int(match.group("version")),
            module_key=match.group("module"),
            surface=match.group("surface"),
            action_key=match.group("action"),
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.version != 1:
            await InteractionRouter._deny(interaction, "Versao desta interacao nao e mais suportada.")
            return
        router = getattr(interaction.client, "platform_interaction_router", None)
        if router is None:
            await InteractionRouter._deny(interaction, "Runtime da plataforma indisponivel.")
            return
        await router.dispatch(
            interaction,
            module_key=self.module_key,
            surface=self.surface,
            action_key=self.action_key,
        )


class RoutedActionSelect(
    discord.ui.DynamicItem[discord.ui.Select],
    template=CUSTOM_ID_PATTERN,
):
    def __init__(
        self,
        item: discord.ui.Select,
        *,
        version: int,
        module_key: str,
        surface: str,
        action_key: str,
    ) -> None:
        super().__init__(item)
        self.version = version
        self.module_key = module_key
        self.surface = surface
        self.action_key = action_key

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Select,
        match: re.Match[str],
    ) -> "RoutedActionSelect":
        del interaction
        return cls(
            item,
            version=int(match.group("version")),
            module_key=match.group("module"),
            surface=match.group("surface"),
            action_key=match.group("action"),
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.version != 1:
            await InteractionRouter._deny(interaction, "Versao desta interacao nao e mais suportada.")
            return
        router = getattr(interaction.client, "platform_interaction_router", None)
        if router is None:
            await InteractionRouter._deny(interaction, "Runtime da plataforma indisponivel.")
            return
        await router.dispatch(
            interaction,
            module_key=self.module_key,
            surface=self.surface,
            action_key=self.action_key,
        )


class RoutedChannelSelect(
    discord.ui.DynamicItem[discord.ui.ChannelSelect],
    template=CUSTOM_ID_PATTERN,
):
    def __init__(self, item, *, version: int, module_key: str, surface: str, action_key: str) -> None:
        super().__init__(item)
        self.version = version
        self.module_key = module_key
        self.surface = surface
        self.action_key = action_key

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        del interaction
        return cls(item, version=int(match.group("version")), module_key=match.group("module"), surface=match.group("surface"), action_key=match.group("action"))

    async def callback(self, interaction: discord.Interaction) -> None:
        router = getattr(interaction.client, "platform_interaction_router", None)
        if self.version != 1 or router is None:
            await InteractionRouter._deny(interaction, "Runtime desta interacao indisponivel.")
            return
        await router.dispatch(interaction, module_key=self.module_key, surface=self.surface, action_key=self.action_key)


class RoutedRoleSelect(
    discord.ui.DynamicItem[discord.ui.RoleSelect],
    template=CUSTOM_ID_PATTERN,
):
    def __init__(self, item, *, version: int, module_key: str, surface: str, action_key: str) -> None:
        super().__init__(item)
        self.version = version
        self.module_key = module_key
        self.surface = surface
        self.action_key = action_key

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        del interaction
        return cls(item, version=int(match.group("version")), module_key=match.group("module"), surface=match.group("surface"), action_key=match.group("action"))

    async def callback(self, interaction: discord.Interaction) -> None:
        router = getattr(interaction.client, "platform_interaction_router", None)
        if self.version != 1 or router is None:
            await InteractionRouter._deny(interaction, "Runtime desta interacao indisponivel.")
            return
        await router.dispatch(interaction, module_key=self.module_key, surface=self.surface, action_key=self.action_key)


class RoutedModal(discord.ui.Modal):
    """Base para modais que voltam ao mesmo router e revalidam permissao."""

    def __init__(
        self,
        *,
        title: str,
        module_key: str,
        surface: str,
        action_key: str,
        panel: dict,
        timeout: float | None = 900,
    ) -> None:
        super().__init__(
            title=title,
            custom_id=custom_id(module_key, surface, action_key),
            timeout=timeout,
        )
        self.module_key = module_key
        self.surface = surface
        self.action_key = action_key
        self.panel = panel

    async def on_submit(self, interaction: discord.Interaction) -> None:
        router = getattr(interaction.client, "platform_interaction_router", None)
        if router is None:
            await InteractionRouter._deny(interaction, "Runtime da plataforma indisponivel.")
            return
        await router.dispatch(
            interaction,
            module_key=self.module_key,
            surface=self.surface,
            action_key=self.action_key,
            panel_override=self.panel,
        )
