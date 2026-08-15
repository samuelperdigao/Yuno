import asyncio
from types import SimpleNamespace
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bot"))

from yuno_bot.domain_modules.registration import ui as registration_ui  # noqa: E402
from yuno_bot.domain_modules.registration.ui import approve  # noqa: E402
from yuno_bot.platform.contracts import ActorContext, RoutedContext  # noqa: E402


class FakeResponse:
    def __init__(self) -> None:
        self.done = False

    def is_done(self) -> bool:
        return self.done

    async def defer(self, **_kwargs) -> None:
        self.done = True


class FakeRole:
    id = 1004
    managed = False

    def __init__(self) -> None:
        self.permissions = SimpleNamespace()
        self.position = 10

    def __le__(self, other) -> bool:
        return self.position <= getattr(other, "position", other)

    def __ge__(self, other) -> bool:
        return self.position >= getattr(other, "position", other)

    def is_default(self) -> bool:
        return False


class FakeMember:
    def __init__(self, events: list[str], role: FakeRole) -> None:
        self.id = 10
        self.nick = "Antes"
        self.roles: list[FakeRole] = []
        self.top_role = FakeRole()
        self.events = events
        self.role = role

    async def edit(self, *, nick, reason) -> None:
        del reason
        self.events.append(f"discord.nick:{nick}")
        self.nick = nick

    async def add_roles(self, role, *, reason) -> None:
        del reason
        self.events.append("discord.role.add")
        self.roles.append(role)

    async def remove_roles(self, role, *, reason) -> None:
        del reason
        self.events.append("discord.role.remove")
        if role in self.roles:
            self.roles.remove(role)


class FakeAPI:
    def __init__(self, events: list[str], *, fail_role_step: bool = False) -> None:
        self.events = events
        self.fail_role_step = fail_role_step
        self.release_payload = None

    async def registration_claim(self, guild_id, request_id, *, actor):
        del guild_id, request_id, actor
        self.events.append("api.claim")
        return {
            "id": "request-1",
            "discord_user_id": "10",
            "operation_token": "opaque-token-value-123456",
            "target_nickname": "Ana | 001",
            "config": {"member_role_id": "1004"},
        }

    async def registration_preflight(self, guild_id, request_id, payload, *, actor):
        del guild_id, request_id, actor
        assert payload["previous_nickname"] == "Antes"
        self.events.append("api.preflight")

    async def registration_step(self, guild_id, request_id, token, step, *, actor):
        del guild_id, request_id, token, actor
        self.events.append(f"api.step.{step}")
        if step == "role" and self.fail_role_step:
            raise RuntimeError("falha ao persistir passo de cargo")

    async def registration_complete(self, guild_id, request_id, token, *, actor):
        del guild_id, request_id, token, actor
        self.events.append("api.complete")

    async def registration_release(
        self, guild_id, request_id, token, *, actor, compensated, error_code
    ):
        del guild_id, request_id, token, actor
        self.events.append("api.release")
        self.release_payload = {"compensated": compensated, "error_code": error_code}


def _context(*, fail_role_step: bool = False):
    events: list[str] = []
    role = FakeRole()
    member = FakeMember(events, role)
    bot_member = SimpleNamespace(
        guild_permissions=SimpleNamespace(manage_roles=True, manage_nicknames=True),
        top_role=SimpleNamespace(position=100),
    )
    guild = SimpleNamespace(
        id=100,
        owner_id=999,
        me=bot_member,
        get_member=lambda user_id: member if user_id == 10 else None,
        get_role=lambda role_id: role if role_id == 1004 else None,
    )
    interaction = SimpleNamespace(guild=guild, response=FakeResponse())
    actor = ActorContext(
        guild_id=100,
        user_id=20,
        role_ids=(9,),
        discord_permissions=(),
        channel_id=1002,
        category_id=None,
        actor_type="user",
        is_guild_owner=False,
        correlation_id="discord-flow",
    )
    api = FakeAPI(events, fail_role_step=fail_role_step)
    return (
        RoutedContext(
            interaction=interaction,
            actor=actor,
            panel={"resource_id": "request-1"},
            api=api,
            receipt_id="receipt-1",
        ),
        events,
        member,
        api,
    )


def test_discord_approval_applies_nickname_before_role_and_finalizes_last() -> None:
    context, events, member, api = _context()
    result = asyncio.run(approve(context))

    assert result.content == "Registro aprovado com nickname e cargo aplicados."
    assert events == [
        "api.claim",
        "api.preflight",
        "discord.nick:Ana | 001",
        "api.step.nickname",
        "discord.role.add",
        "api.step.role",
        "api.complete",
    ]
    assert member.nick == "Ana | 001"
    assert api.release_payload is None


def test_discord_approval_compensates_only_role_added_and_restores_nickname() -> None:
    context, events, member, api = _context(fail_role_step=True)
    result = asyncio.run(approve(context))

    assert "falha ao persistir" in result.content
    assert events == [
        "api.claim",
        "api.preflight",
        "discord.nick:Ana | 001",
        "api.step.nickname",
        "discord.role.add",
        "api.step.role",
        "discord.role.remove",
        "discord.nick:Antes",
        "api.release",
    ]
    assert member.nick == "Antes"
    assert member.roles == []
    assert api.release_payload == {"compensated": True, "error_code": "RuntimeError"}


def test_panel_recovery_activates_registration_after_visual_reconciliation(monkeypatch) -> None:
    events: list[str] = []

    async def reconcile(_self, **kwargs):
        assert kwargs["module_key"] == "registration"
        assert kwargs["panel_key"] == "public"
        events.append("panel.reconciled")

    class FakeAPI:
        async def registration_config(self, guild_id):
            assert guild_id == 100
            return {
                "version": 3,
                "data": {"panel_channel_id": "200", "enabled": True},
            }

        async def module_instance(self, guild_id, module_key):
            assert (guild_id, module_key) == (100, "registration")
            return {"lifecycle": "inactive"}

        async def update_lifecycle(
            self, guild_id, module_key, *, lifecycle, expected_lifecycle, actor, reason
        ):
            assert (guild_id, module_key) == (100, "registration")
            assert lifecycle == "active"
            assert expected_lifecycle == "inactive"
            assert actor.actor_type == "system"
            assert reason
            events.append("lifecycle.active")

    monkeypatch.setattr(registration_ui.PanelPublisher, "reconcile", reconcile)
    guild = SimpleNamespace(id=100)
    bot = SimpleNamespace(
        user=SimpleNamespace(id=999),
        get_guild=lambda guild_id: guild if guild_id == 100 else None,
    )
    result = asyncio.run(
        registration_ui.run_job(
            bot,
            FakeAPI(),
            {
                "guild_id": "100",
                "key": "registration.panel.reconcile",
                "correlation_id": "panel-recovery",
            },
        )
    )

    assert events == ["panel.reconciled", "lifecycle.active"]
    assert result == {"changed": True, "panel_key": "public", "activated": True}


def test_registration_admin_uses_five_clear_configuration_steps() -> None:
    selector = registration_ui._section_select()
    options = selector["options"]

    assert [item["value"] for item in options] == [
        "channels",
        "team",
        "rules",
        "panel",
        "messages",
    ]
    assert [item["label"] for item in options] == [
        "1 · Canais",
        "2 · Equipe e cargo",
        "3 · Regras do formulário",
        "4 · Aparência do painel",
        "5 · Mensagens",
    ]


def test_panel_color_is_selected_by_name_and_not_typed_as_hex() -> None:
    options = registration_ui._panel_color_options("#ED4245")
    labels = {item["label"] for item in options}

    assert {"Amarelo Yuno", "Vermelho", "Branco"} <= labels
    assert next(item for item in options if item["label"] == "Vermelho")["default"] is True
    assert all(field[0] != "panel_color" for field in registration_ui.CONFIG_MODAL_FIELDS["panel"])
    assert any(field[0] == "panel_banner_url" for field in registration_ui.CONFIG_MODAL_FIELDS["panel"])
    assert all(
        field[0] != "panel_thumbnail_url"
        for fields in registration_ui.CONFIG_MODAL_FIELDS.values()
        for field in fields
    )


def test_registration_rules_use_two_clear_single_choice_selects() -> None:
    numeric = registration_ui._id_format_options(True)
    alphanumeric = registration_ui._id_format_options(False)
    allow = registration_ui._resubmit_policy_options(True)
    block = registration_ui._resubmit_policy_options(False)

    assert [item["value"] for item in numeric] == ["numeric", "alphanumeric"]
    assert [item["default"] for item in numeric] == [True, False]
    assert [item["default"] for item in alphanumeric] == [False, True]
    assert "12345" in numeric[0]["description"]
    assert "ABC123" in numeric[1]["description"]
    assert [item["value"] for item in allow] == ["allow", "block"]
    assert [item["default"] for item in allow] == [True, False]
    assert [item["default"] for item in block] == [False, True]

    components = registration_ui._rules_section_components(
        {
            "player_id_numeric_only": True,
            "allow_resubmit_after_rejection": True,
            "player_id_min_length": 1,
            "player_id_max_length": 16,
            "name_min_length": 2,
            "name_max_length": 24,
        }
    )
    selects = [
        row["components"][0]
        for row in components
        if row["type"] == 1 and row["components"][0]["type"] == 3
    ]
    assert [select["custom_id"].rsplit(":", 1)[-1] for select in selects] == [
        "set_id_format",
        "set_resubmit_policy",
    ]
    assert all(select["min_values"] == select["max_values"] == 1 for select in selects)


def test_registration_rule_handlers_change_only_the_selected_rule(monkeypatch) -> None:
    saved: list[dict] = []
    rendered: list[str] = []

    async def defer(_interaction) -> None:
        return None

    async def save(_interaction, _api, patch: dict) -> None:
        saved.append(patch)

    async def render(_interaction, _api, section: str) -> None:
        rendered.append(section)

    monkeypatch.setattr(registration_ui, "_defer_if_needed", defer)
    monkeypatch.setattr(registration_ui, "_save_patch", save)
    monkeypatch.setattr(registration_ui, "_render_section", render)

    asyncio.run(
        registration_ui.set_id_format(
            SimpleNamespace(data={"values": ["alphanumeric"]}), object()
        )
    )
    asyncio.run(
        registration_ui.set_resubmit_policy(
            SimpleNamespace(data={"values": ["block"]}), object()
        )
    )

    assert saved == [
        {"player_id_numeric_only": False},
        {"allow_resubmit_after_rejection": False},
    ]
    assert rendered == ["rules", "rules"]


def test_central_replacement_acknowledges_silently_without_receipt(monkeypatch) -> None:
    calls: list[tuple] = []

    class SilentResponse:
        done = False

        def is_done(self) -> bool:
            return self.done

        async def defer(self, **kwargs) -> None:
            calls.append(("defer", kwargs))
            self.done = True

    async def edit_message(bot, channel_id, message_id, data) -> None:
        calls.append(("edit", bot, channel_id, message_id, data))

    monkeypatch.setattr(registration_ui, "edit_message", edit_message)
    interaction = SimpleNamespace(
        response=SilentResponse(),
        client="bot",
        channel_id=10,
        message=SimpleNamespace(id=20),
    )

    asyncio.run(registration_ui._replace_central(interaction, {"components": []}))

    assert calls == [
        ("defer", {}),
        ("edit", "bot", 10, 20, {"components": []}),
    ]


def test_unpublished_admin_summary_hides_internal_state(monkeypatch) -> None:
    captured: dict = {}

    async def admin_state(api, guild_id):
        del api, guild_id
        return (
            {"lifecycle": "inactive"},
            {
                "base_published_version": None,
                "data": {
                    "panel_channel_id": "",
                    "approval_channel_id": "",
                    "member_role_id": "",
                    "approver_role_ids": [],
                },
            },
        )

    async def replace_central(interaction, data, **kwargs):
        del interaction, kwargs
        captured.update(data)

    monkeypatch.setattr(registration_ui, "_admin_state", admin_state)
    monkeypatch.setattr(registration_ui, "_replace_central", replace_central)

    asyncio.run(registration_ui.render_admin(SimpleNamespace(guild_id=100), object()))

    children = captured["components"][0]["components"]
    content = "\n".join(item["content"] for item in children if item["type"] == 10)
    action = next(item for item in children if item["type"] == 1)
    button_data = action["components"][0]
    assert "Ainda não publicado" in content
    assert "lifecycle" not in content.lower()
    assert "rascunho" not in content.lower()
    assert button_data["label"] == "Configurar Registro"
    assert button_data["style"] == 2
    assert "emoji" not in button_data


def test_published_admin_summary_has_clean_visual_hierarchy() -> None:
    data = registration_ui.build_admin_payload(
        {"lifecycle": "active"},
        {
            "base_published_version": 2,
            "data": {
                "panel_channel_id": "10",
                "approval_channel_id": "20",
                "member_role_id": "30",
                "approver_role_ids": ["40"],
            },
        },
    )
    children = data["components"][0]["components"]
    content = "\n".join(item["content"] for item in children if item["type"] == 10)

    assert content.startswith("# Registro")
    assert "### Status" in content
    assert "### Fluxo atual" in content
    assert "<#10>" in content
    assert "<#20>" in content
    assert "<@&30>" in content
    assert not {"📍", "🔎", "🎭", "👥", "✅"}.intersection(content)
