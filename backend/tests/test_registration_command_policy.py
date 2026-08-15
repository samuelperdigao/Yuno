import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import discord
from discord import app_commands


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bot"))

from yuno_bot import main as bot_main  # noqa: E402
from yuno_bot.main import apply_control_plane_command_policy  # noqa: E402


def test_control_plane_keeps_only_yuno_configurar_and_registration_adds_no_slash() -> None:
    client = discord.Client(intents=discord.Intents.none())
    tree = app_commands.CommandTree(client)
    yuno = app_commands.Group(name="yuno", description="Yuno")

    @yuno.command(name="configurar")
    async def configurar(_interaction: discord.Interaction) -> None:
        pass

    @yuno.command(name="status")
    async def status(_interaction: discord.Interaction) -> None:
        pass

    @tree.command(name="registro")
    async def registro(_interaction: discord.Interaction) -> None:
        pass

    tree.add_command(yuno)
    removed = apply_control_plane_command_policy(tree)

    assert [command.name for command in tree.get_commands()] == ["yuno"]
    remaining_yuno = tree.get_command("yuno")
    assert isinstance(remaining_yuno, app_commands.Group)
    assert [command.name for command in remaining_yuno.commands] == ["configurar"]
    assert removed == ["/registro", "/yuno status"]

    registration_sources = list(
        (ROOT / "bot" / "yuno_bot" / "domain_modules" / "registration").glob("*.py")
    )
    source = "\n".join(path.read_text(encoding="utf-8") for path in registration_sources)
    assert "app_commands" not in source


def test_control_plane_configure_uses_current_channel_without_legacy_setup(monkeypatch) -> None:
    events: list[str] = []

    class FakeMember:
        id = 20

    class FakeTextChannel:
        id = 30
        mention = "<#30>"

    class FakeResponse:
        async def defer(self, **_kwargs) -> None:
            events.append("defer")

    class FakeFollowup:
        async def send(self, content, **_kwargs) -> None:
            events.append(content)

    class FakeAPI:
        async def save_guild_config(self, guild_id, config, *, actor_id):
            assert guild_id == 10
            assert actor_id == 20
            assert config["settings"]["dashboard"] == {
                "panel_channel_id": "30",
                "panel_message_id": "40",
            }
            events.append("saved")
            return config

    async def scenario() -> None:
        async def current_config(_interaction):
            return {"settings": {"preserved": True}}

        async def fetch_states(*_args, **_kwargs):
            return {"registration": {"configured": False}}

        async def publish(*_args, **_kwargs):
            events.append("published")
            return 40

        async def remove_previous(*_args, **_kwargs):
            events.append("old_removed")

        async def forbidden_setup(*_args, **_kwargs):
            raise AssertionError("Control Plane nao pode recriar estrutura legada")

        monkeypatch.setattr(bot_main.discord, "Member", FakeMember)
        monkeypatch.setattr(bot_main.discord, "TextChannel", FakeTextChannel)
        monkeypatch.setattr(
            bot_main, "get_settings", lambda: SimpleNamespace(control_plane_enabled=True)
        )
        monkeypatch.setattr(bot_main, "is_control_plane_admin", lambda *_args: True)
        monkeypatch.setattr(bot_main.dashboard, "fetch_control_states", fetch_states)
        monkeypatch.setattr(bot_main.dashboard, "publish_or_update", publish)
        monkeypatch.setattr(bot_main.dashboard, "remove_previous_dashboard", remove_previous)
        monkeypatch.setattr(bot_main.server_setup, "ensure_setup_channels", forbidden_setup)

        bot = SimpleNamespace(api=FakeAPI(), platform_api=object())
        cog = bot_main.YunoAdminCog(bot)
        monkeypatch.setattr(cog, "_carregar_config", current_config)
        interaction = SimpleNamespace(
            guild=SimpleNamespace(id=10),
            user=FakeMember(),
            channel=FakeTextChannel(),
            response=FakeResponse(),
            followup=FakeFollowup(),
        )
        await bot_main.YunoAdminCog.yuno_configurar.callback(cog, interaction)

    asyncio.run(scenario())
    assert events == [
        "defer",
        "published",
        "saved",
        "old_removed",
        "Central reconciliada e publicada em <#30>.",
    ]


def test_registration_sweeper_schedules_every_expired_claim() -> None:
    scheduled: list[tuple[int, str, dict]] = []

    class FakeAPI:
        async def registration_stale(self, guild_id):
            assert guild_id == 10
            return [{"id": "request-1", "revision": 7}]

        async def schedule_task(self, guild_id, module_key, payload):
            scheduled.append((guild_id, module_key, payload))

    fake_bot = SimpleNamespace(
        guilds=[SimpleNamespace(id=10)],
        platform_api=FakeAPI(),
        log=SimpleNamespace(exception=lambda *_args, **_kwargs: None),
    )
    asyncio.run(bot_main.YunoBot.sweep_registration_recovery_once(fake_bot))

    assert len(scheduled) == 1
    guild_id, module_key, payload = scheduled[0]
    assert (guild_id, module_key) == (10, "registration")
    assert payload["job_key"] == "registration.processing.recover"
    assert payload["resource_id"] == "request-1"
    assert payload["idempotency_key"] == "stale:request-1:7"
