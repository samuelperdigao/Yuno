import functools
from typing import Any, Awaitable, Callable, TypeVar

import discord

from yuno_bot.api_client import YunoAPI

_ViewMethod = TypeVar("_ViewMethod", bound=Callable[..., Awaitable[None]])


async def ensure_allowed(interaction: discord.Interaction, api: YunoAPI, module: str, command: str) -> tuple[bool, str]:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return False, "Este comando precisa ser usado dentro de um servidor."

    category_id = None
    if isinstance(interaction.channel, discord.TextChannel) and interaction.channel.category:
        category_id = interaction.channel.category.id

    return await api.check_permission(
        guild_id=interaction.guild.id,
        module=module,
        command=command,
        role_ids=[role.id for role in interaction.user.roles],
        channel_id=interaction.channel_id,
        category_id=category_id,
    )


async def deny(interaction: discord.Interaction, reason: str) -> None:
    await interaction.response.send_message(f"Yuno nao pode executar isso agora: {reason}", ephemeral=True)


def _view_api(view: Any) -> YunoAPI:
    """Extrai o YunoAPI de uma View persistente, qualquer que seja o atributo usado para guardar a dependencia."""
    api = getattr(view, "api", None)
    if api is not None:
        return api
    return view.controller.bot.api


def requires_module(module: str, command: str) -> Callable[[_ViewMethod], _ViewMethod]:
    """Guard de callback de botao: nega antes de executar se o modulo estiver desligado, sem licenca ou sem permissao.

    Cobre o mesmo `check_permission` que os slash commands ja usam via `ensure_allowed`,
    entao um modulo desligado no dashboard fica bloqueado tanto no comando quanto no painel.
    """

    def decorator(func: _ViewMethod) -> _ViewMethod:
        @functools.wraps(func)
        async def wrapper(self: Any, interaction: discord.Interaction, *args: Any, **kwargs: Any) -> None:
            allowed, reason = await ensure_allowed(interaction, _view_api(self), module, command)
            if not allowed:
                await deny(interaction, reason)
                return
            await func(self, interaction, *args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
