import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import discord
import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "bot"))

from yuno_bot.guards import requires_module


class FakeInteraction:
    def __init__(self, *, guild_id: int = 1, role_ids: list[int] | None = None) -> None:
        self.guild = SimpleNamespace(id=guild_id)
        member = MagicMock(spec=discord.Member)
        member.roles = [SimpleNamespace(id=role_id) for role_id in role_ids or []]
        self.user = member
        self.channel = None
        self.channel_id = None
        self.sent: list[tuple[str, bool]] = []
        self.response = SimpleNamespace(send_message=self._send_message)

    async def _send_message(self, content: str, *, ephemeral: bool = False) -> None:
        self.sent.append((content, ephemeral))


class FakeApi:
    def __init__(self, *, module_enabled: bool) -> None:
        self.module_enabled = module_enabled

    async def check_permission(self, **kwargs) -> tuple[bool, str]:
        if not self.module_enabled:
            return False, "Modulo desativado para este servidor."
        return True, "Permitido."


class FakeView:
    def __init__(self, api: FakeApi) -> None:
        self.api = api
        self.called = False

    @requires_module("meta", "definir")
    async def definir(self, interaction: FakeInteraction) -> None:
        self.called = True


@pytest.mark.asyncio
async def test_requires_module_denies_and_skips_callback_when_module_disabled() -> None:
    view = FakeView(FakeApi(module_enabled=False))
    interaction = FakeInteraction()

    await view.definir(interaction)

    assert view.called is False
    assert interaction.sent == [("Yuno nao pode executar isso agora: Modulo desativado para este servidor.", True)]


@pytest.mark.asyncio
async def test_requires_module_calls_callback_when_module_enabled() -> None:
    view = FakeView(FakeApi(module_enabled=True))
    interaction = FakeInteraction()

    await view.definir(interaction)

    assert view.called is True
    assert interaction.sent == []


@pytest.mark.asyncio
async def test_requires_module_reads_api_from_controller_when_view_has_no_api_attribute() -> None:
    class FakeController:
        def __init__(self, api: FakeApi) -> None:
            self.bot = SimpleNamespace(api=api)

    class FarmLikeView:
        def __init__(self, controller: FakeController) -> None:
            self.controller = controller
            self.called = False

        @requires_module("farm_tickets", "abrir")
        async def open_ticket(self, interaction: FakeInteraction) -> None:
            self.called = True

    view = FarmLikeView(FakeController(FakeApi(module_enabled=False)))
    interaction = FakeInteraction()

    await view.open_ticket(interaction)

    assert view.called is False
    assert interaction.sent[0][0] == "Yuno nao pode executar isso agora: Modulo desativado para este servidor."
