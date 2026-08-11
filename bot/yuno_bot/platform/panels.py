from __future__ import annotations

import discord

from yuno_bot.platform.contracts import ActorContext
from yuno_bot.platform.registry import UIRegistry, ui_registry


class PanelPublisher:
    """Publica e recupera paineis domain-first com compensacao Discord/API."""

    def __init__(self, bot: discord.Client, api, registry: UIRegistry | None = None) -> None:
        self.bot = bot
        self.api = api
        self.registry = registry or ui_registry

    async def reconcile(
        self,
        *,
        guild: discord.Guild,
        module_key: str,
        panel_key: str,
        channel_id: int,
        actor: ActorContext,
        resource_type: str = "",
        resource_id: str = "",
        render_context: dict | None = None,
    ) -> dict:
        definition = self.registry.panel(module_key, panel_key)
        if definition is None:
            raise LookupError(f"Painel '{module_key}:{panel_key}' nao registrado.")
        correlation_id = actor.correlation_id
        actor_id = actor.user_id or getattr(self.bot.user, "id", None)
        if actor_id is None:
            raise RuntimeError("Nao foi possivel identificar o ator da publicacao.")
        panel = await self.api.ensure_panel(
            guild.id,
            module_key,
            {
                "panel_key": panel_key,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "definition_version": definition.version,
                "recovery_policy": definition.recovery_policy,
                "actor": actor.as_payload(),
            },
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        if panel["state"] == "archived":
            raise RuntimeError("Painel arquivado nao pode ser republicado.")
        channel = guild.get_channel(channel_id)
        if channel is None:
            channel = await guild.fetch_channel(channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            raise TypeError("O destino do painel precisa ser um canal de texto ou thread.")
        payload = await definition.renderer(
            {
                "guild": guild,
                "panel": panel,
                "resource_type": resource_type,
                "resource_id": resource_id,
                **(render_context or {}),
            }
        )

        old_message = await self._resolve_existing_message(guild, panel)
        if old_message is not None and old_message.channel.id == channel.id:
            await old_message.edit(**payload)
            return await self._update(
                guild.id,
                panel,
                actor_id,
                actor,
                correlation_id,
                state="published",
                channel_id=str(channel.id),
                message_id=str(old_message.id),
                verified=True,
                last_error=None,
            )

        if (
            old_message is None
            and panel.get("message_id")
            and panel["state"] in {"published", "paused"}
        ):
            panel = await self._update(
                guild.id,
                panel,
                actor_id,
                actor,
                correlation_id,
                state="missing",
                last_error="Mensagem do painel nao encontrada.",
                verified=True,
            )
        if panel["state"] in {"draft", "missing", "error"}:
            panel = await self._update(
                guild.id,
                panel,
                actor_id,
                actor,
                correlation_id,
                state="ready",
                last_error=None,
            )
        new_message = await channel.send(**payload)
        try:
            updated = await self._update(
                guild.id,
                panel,
                actor_id,
                actor,
                correlation_id,
                state="published",
                channel_id=str(channel.id),
                message_id=str(new_message.id),
                verified=True,
                last_error=None,
            )
        except Exception:
            await self._delete_if_owned(new_message)
            raise
        if old_message is not None:
            await self._delete_if_owned(old_message)
        return updated

    async def recover(self, **kwargs) -> dict:
        return await self.reconcile(**kwargs)

    async def _resolve_existing_message(
        self, guild: discord.Guild, panel: dict
    ) -> discord.Message | None:
        channel_id = panel.get("channel_id")
        message_id = panel.get("message_id")
        if not channel_id or not message_id:
            return None
        channel = guild.get_channel(int(channel_id))
        if channel is None:
            try:
                channel = await guild.fetch_channel(int(channel_id))
            except discord.NotFound:
                return None
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return None
        try:
            return await channel.fetch_message(int(message_id))
        except discord.NotFound:
            return None

    async def _update(
        self,
        guild_id: int,
        panel: dict,
        actor_id: int,
        actor: ActorContext,
        correlation_id: str,
        **changes,
    ) -> dict:
        return await self.api.update_panel(
            guild_id,
            panel["id"],
            {
                "expected_render_revision": panel["render_revision"],
                "actor": actor.as_payload(),
                **changes,
            },
            actor_id=actor_id,
            correlation_id=correlation_id,
        )

    async def _delete_if_owned(self, message: discord.Message) -> None:
        if self.bot.user is not None and message.author.id == self.bot.user.id:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
