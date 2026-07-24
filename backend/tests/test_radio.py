import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "bot"))

from yuno_bot.commands.radio.embeds import criar_embed_painel_radio
from yuno_bot.commands.radio.permissions import configurar_permissoes_radio, pode_alterar_radio


class FakeRole:
    def __init__(self, name: str):
        self.name = name


class FakeMember:
    def __init__(self, *, administrator: bool = False, roles: list[FakeRole] | None = None):
        self.guild_permissions = SimpleNamespace(administrator=administrator)
        self.roles = roles or []


class FakeTextChannel:
    def __init__(self):
        self.guild = SimpleNamespace(default_role=FakeRole("@everyone"), me=FakeMember())
        self.overwrites = {}
        self.edited_overwrites = None
        self.edit_reason = None

    async def edit(self, *, overwrites, reason: str):
        self.edited_overwrites = overwrites
        self.edit_reason = reason


def test_radio_panel_embed_matches_requested_layout() -> None:
    embed = criar_embed_painel_radio()
    data = embed.to_dict()

    assert data["title"] == "📻 Central de Rádio"
    assert data["fields"][0]["name"] == "📡 Como alterar"
    assert data["fields"][1]["name"] == "🔒 Acesso restrito"
    assert data["footer"]["text"] == "Yuno • Sistema de Rádio"
    assert "timestamp" not in data


def test_radio_admin_can_change_radio() -> None:
    assert pode_alterar_radio(FakeMember(administrator=True)) is True


def test_radio_gerente_role_can_change_radio() -> None:
    member = FakeMember(roles=[FakeRole("SubGerente Operacional")])
    assert pode_alterar_radio(member) is True


def test_radio_regular_member_cannot_change_radio() -> None:
    member = FakeMember(roles=[FakeRole("Membro")])
    assert pode_alterar_radio(member) is False


@pytest.mark.asyncio
async def test_radio_permissions_block_members_from_sending_messages_and_threads() -> None:
    channel = FakeTextChannel()

    await configurar_permissoes_radio(channel)

    default_overwrite = channel.edited_overwrites[channel.guild.default_role]
    assert default_overwrite.send_messages is False
    assert default_overwrite.send_messages_in_threads is False
    assert default_overwrite.create_public_threads is False
    assert default_overwrite.create_private_threads is False
    assert default_overwrite.view_channel is None


@pytest.mark.asyncio
async def test_radio_permissions_allow_bot_to_send_embeds_and_mention_everyone() -> None:
    channel = FakeTextChannel()

    await configurar_permissoes_radio(channel)

    bot_overwrite = channel.edited_overwrites[channel.guild.me]
    assert bot_overwrite.view_channel is True
    assert bot_overwrite.send_messages is True
    assert bot_overwrite.embed_links is True
    assert bot_overwrite.mention_everyone is True
    assert channel.edit_reason == "Canal da rádio reservado ao painel interativo"
