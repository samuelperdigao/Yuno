import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import discord
import httpx
import pytest
from discord import app_commands
from pydantic import ValidationError

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "bot"))

from yuno_bot import dashboard
from yuno_bot.commands.meta.control_plane import (
    MetaConfig,
    build_panel_embed,
    diagnose_state,
    project_to_legacy,
    publish_draft,
    seed_from_legacy,
    validate,
)
from yuno_bot.control_plane import is_control_plane_admin, pending_changes
from yuno_bot.config import BotSettings
from yuno_bot.main import apply_control_plane_command_policy
from yuno_bot.modules import discover_modules


VALID_META = {
    "panel_channel_id": "101",
    "result_channel_id": "102",
    "allowed_role_id": "103",
    "default_items": [{"name": "Kit Desmanche", "quantity": 50}],
    "panel": {
        "title": "Metas Semanais",
        "description": "Consulte e defina as metas da organização.",
        "color": "#FFC72C",
    },
}


def test_control_plane_flag_is_explicit_and_defaults_to_rollback_mode() -> None:
    assert BotSettings(discord_bot_token="test-token").control_plane_enabled is False
    assert BotSettings(
        discord_bot_token="test-token", control_plane_enabled=True
    ).control_plane_enabled is True


def test_meta_model_accepts_valid_config_and_rejects_invalid_values() -> None:
    assert MetaConfig.model_validate(VALID_META).default_items[0].quantity == 50

    for patch in (
        {"default_items": [{"name": "Kit", "quantity": 0}]},
        {"default_items": [{"name": "Kit", "quantity": 1}, {"name": "KIT", "quantity": 2}]},
        {"panel": {**VALID_META["panel"], "color": "amarelo"}},
        {"campo_desconhecido": True},
    ):
        candidate = {**VALID_META, **patch}
        with pytest.raises(ValidationError):
            MetaConfig.model_validate(candidate)


def test_meta_model_enforces_item_and_text_limits() -> None:
    with pytest.raises(ValidationError):
        MetaConfig.model_validate(
            {**VALID_META, "default_items": [{"name": str(index), "quantity": 1} for index in range(21)]}
        )
    with pytest.raises(ValidationError):
        MetaConfig.model_validate(
            {**VALID_META, "panel": {**VALID_META["panel"], "title": "x" * 257}}
        )


def test_seed_from_legacy_imports_identity_messages_permissions_and_items() -> None:
    legacy = {
        "settings": {
            "meta": {
                "panel_channel_id": "11",
                "result_channel_id": "12",
                "last_definition_text": "Kit Desmanche, 50",
            }
        },
        "messages": {
            "meta": {"panel": {"title": "Meta da Cidade", "description": "Desc", "color": "#123ABC"}}
        },
        "command_permissions": {"meta.definir": {"role_ids": ["13"]}},
    }
    seeded = seed_from_legacy(legacy)
    assert seeded["panel_channel_id"] == "11"
    assert seeded["result_channel_id"] == "12"
    assert seeded["allowed_role_id"] == "13"
    assert seeded["default_items"] == [{"name": "Kit Desmanche", "quantity": 50}]
    assert seeded["panel"]["title"] == "Meta da Cidade"


def test_incomplete_legacy_seed_is_diagnostic_not_fatal() -> None:
    seeded = seed_from_legacy(
        {
            "settings": {
                "meta": {"panel_channel_id": "11", "last_definition_text": "invalido"}
            },
            "messages": {"meta": {"panel": {"color": "cor-invalida"}}},
        }
    )
    assert seeded["panel_channel_id"] == "11"
    errors, warnings = validate(seeded)
    assert errors
    assert warnings == []


def test_meta_projection_contains_runtime_contract_and_renderer() -> None:
    projection = project_to_legacy(
        VALID_META,
        {"panel_channel_id": "101", "panel_message_id": "104"},
        True,
    )
    assert projection["settings"]["panel_message_id"] == "104"
    assert projection["settings"]["default_items"] == VALID_META["default_items"]
    assert projection["messages"]["color"] == "#FFC72C"
    assert projection["command_permissions"]["meta.definir"]["role_ids"] == ["103"]
    assert projection["enabled"] is True

    embed = build_panel_embed(VALID_META, "Cidade Teste")
    assert embed.title == "Metas Semanais"
    assert embed.description == VALID_META["panel"]["description"]
    assert embed.color.value == 0xFFC72C


def test_only_meta_has_control_plane_contract_and_pending_state_is_explicit() -> None:
    registry = discover_modules(force=True)
    assert registry["meta"].control_plane is not None
    assert registry["meta"].control_plane.schema_version == 1
    assert all(spec.control_plane is None for key, spec in registry.items() if key != "meta")
    state = {
        "draft_revision": 2,
        "published_revision": 1,
        "draft_data": {"x": 2},
        "published_data": {"x": 1},
    }
    assert pending_changes(state) is True
    errors, warnings = diagnose_state({}, state)
    assert errors
    assert any("pendentes" in warning for warning in warnings)


def test_dashboard_never_suggests_legacy_slash_and_marks_unmigrated_modules() -> None:
    registry = discover_modules()
    config = {"modules": {key: True for key in registry}, "settings": {}}
    set_embed = dashboard.module_info_embed(registry["set"], config)
    assert any(field.value == "Migração para a Central pendente." for field in set_embed.fields)
    assert not any("/set" in str(field.value) for field in set_embed.fields)

    payload_text = str(dashboard.build_payload(config, control_states={"meta": {}}))
    assert "Migração para a Central pendente" in payload_text
    assert "/meta" not in payload_text


def test_command_tree_policy_keeps_only_yuno_configurar_globally_and_for_test_guild() -> None:
    client = discord.Client(intents=discord.Intents.none())
    tree = app_commands.CommandTree(client)
    yuno = app_commands.Group(name="yuno", description="Yuno")

    @yuno.command(name="configurar", description="Configurar")
    async def configurar(interaction: discord.Interaction) -> None:
        pass

    @yuno.command(name="status", description="Status")
    async def status(interaction: discord.Interaction) -> None:
        pass

    tree.add_command(yuno)
    tree.add_command(app_commands.Group(name="meta", description="Meta"))
    tree.add_command(app_commands.Group(name="setup_farm", description="Farm"))

    removed = apply_control_plane_command_policy(tree)
    assert removed == ["/meta", "/setup_farm", "/yuno status"]
    assert [(command.name, [child.name for child in command.commands]) for command in tree.get_commands()] == [
        ("yuno", ["configurar"])
    ]

    guild = discord.Object(id=123)
    tree.copy_global_to(guild=guild)
    assert [(command.name, [child.name for child in command.commands]) for command in tree.get_commands(guild=guild)] == [
        ("yuno", ["configurar"])
    ]
    asyncio.run(client.close())


def test_admin_permission_accepts_owner_manage_guild_and_configured_role() -> None:
    def member(member_id: int, *, manage: bool = False, admin: bool = False, roles=()):
        return SimpleNamespace(
            id=member_id,
            guild_permissions=SimpleNamespace(manage_guild=manage, administrator=admin),
            roles=[SimpleNamespace(id=role_id) for role_id in roles],
        )

    guild = SimpleNamespace(owner_id=1)
    assert is_control_plane_admin(guild, member(1), {})
    assert is_control_plane_admin(guild, member(2, manage=True), {})
    assert is_control_plane_admin(guild, member(3, admin=True), {})
    assert is_control_plane_admin(guild, member(4, roles=(99,)), {"admin_role_ids": ["99"]})
    assert not is_control_plane_admin(guild, member(5), {"admin_role_ids": ["99"]})


def test_meta_publication_create_update_move_and_rollback(monkeypatch) -> None:
    class Permissions:
        view_channel = True
        send_messages = True
        embed_links = True
        mention_everyone = True

    class FakeMessage:
        def __init__(self, message_id, channel, author_id=999):
            self.id = message_id
            self.channel = channel
            self.author = SimpleNamespace(id=author_id)
            self.edits = []
            self.deleted = False

        async def edit(self, *, embed, view):
            self.edits.append(embed.title)

        async def delete(self):
            self.deleted = True

    class FakeTextChannel:
        def __init__(self, channel_id, guild):
            self.id = channel_id
            self.guild = guild
            self.messages = {}
            self.sent = []

        def permissions_for(self, member):
            return Permissions()

        async def fetch_message(self, message_id):
            return self.messages[message_id]

        async def send(self, *, embed, view, allowed_mentions):
            message = FakeMessage(500 + len(self.sent), self)
            self.messages[message.id] = message
            self.sent.append(message)
            return message

    class FakeGuild:
        def __init__(self):
            self.id = 77
            self.name = "Cidade Teste"
            self.me = SimpleNamespace(id=999)
            self.channels = {}

        def get_channel(self, channel_id):
            return self.channels.get(channel_id)

        def get_role(self, role_id):
            return SimpleNamespace(id=role_id) if role_id == 103 else None

    class FakeAPI:
        def __init__(self, fail=False):
            self.fail = fail
            self.calls = []

        async def publish_module_config(self, guild_id, module_key, **kwargs):
            self.calls.append((guild_id, module_key, kwargs))
            if self.fail:
                raise httpx.ConnectError("falha simulada")
            return {"published_revision": 2}

    monkeypatch.setattr(discord, "TextChannel", FakeTextChannel)

    async def scenarios():
        guild = FakeGuild()
        old_channel = FakeTextChannel(100, guild)
        target = FakeTextChannel(101, guild)
        guild.channels = {100: old_channel, 101: target, 102: FakeTextChannel(102, guild)}
        interaction = SimpleNamespace(guild=guild, user=SimpleNamespace(id=42))
        state = {
            "draft_revision": 2,
            "draft_data": VALID_META,
            "published_revision": 1,
            "published_data": {**VALID_META, "panel": {**VALID_META["panel"], "title": "Versão antiga"}},
        }

        api = FakeAPI()
        created = await publish_draft(interaction, api, state, {"modules": {"meta": True}, "settings": {}})
        assert created["published_revision"] == 2
        assert len(target.sent) == 1
        assert api.calls[0][2]["panel_refs"]["panel_channel_id"] == "101"

        existing = FakeMessage(600, target)
        target.messages[600] = existing
        config_same = {
            "modules": {"meta": True},
            "settings": {"meta": {"panel_channel_id": "101", "panel_message_id": "600"}},
        }
        await publish_draft(interaction, FakeAPI(), state, config_same)
        assert existing.edits == ["Metas Semanais"]
        assert len(target.sent) == 1

        old_message = FakeMessage(700, old_channel)
        old_channel.messages[700] = old_message
        config_move = {
            "modules": {"meta": True},
            "settings": {"meta": {"panel_channel_id": "100", "panel_message_id": "700"}},
        }
        await publish_draft(interaction, FakeAPI(), state, config_move)
        assert old_message.deleted is True

        failing_new_api = FakeAPI(fail=True)
        sent_before = len(target.sent)
        with pytest.raises(httpx.HTTPError):
            await publish_draft(
                interaction,
                failing_new_api,
                state,
                {"modules": {"meta": True}, "settings": {}},
            )
        assert len(target.sent) == sent_before + 1
        assert target.sent[-1].deleted is True

        restore_message = FakeMessage(800, target)
        target.messages[800] = restore_message
        config_restore = {
            "modules": {"meta": True},
            "settings": {"meta": {"panel_channel_id": "101", "panel_message_id": "800"}},
        }
        with pytest.raises(httpx.HTTPError):
            await publish_draft(interaction, FakeAPI(fail=True), state, config_restore)
        assert restore_message.edits == ["Metas Semanais", "Versão antiga"]

    asyncio.run(scenarios())
