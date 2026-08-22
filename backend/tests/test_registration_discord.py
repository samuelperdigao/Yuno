import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bot"))

from yuno_bot.domain_modules.registration import ui as registration_ui  # noqa: E402
from yuno_bot.domain_modules.registration.renderers import (  # noqa: E402
    APPROVED_COLOR,
    REJECTED_COLOR,
    RegistrationLogData,
    RegistrationLogRenderer,
)
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

    assert result.content == "Registro aprovado com apelido e cargo aplicados."
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


def test_registration_log_renderer_builds_commercial_approved_and_rejected_embeds() -> None:
    renderer = RegistrationLogRenderer()
    approved_data = RegistrationLogData.from_payload(
        {
            "decision": "approved",
            "discord_user_id": "10",
            "submitted_name": "Ana Silva",
            "player_id": "001",
            "reviewed_by": "20",
            "target_nickname": "Ana Silva | 001",
            "member_role_id": "30",
            "decision_at": "2026-08-22T12:05:00+00:00",
            "log_approved_title": "Acesso liberado",
            "log_footer": "Yuno • Organização",
        },
        avatar_url="https://cdn.discordapp.com/avatar.png",
    )
    approved = renderer.render_approved(approved_data).to_dict()
    approved_fields = {item["name"]: item["value"] for item in approved["fields"]}

    assert approved["title"] == "Acesso liberado"
    assert approved["color"] == APPROVED_COLOR
    assert approved["thumbnail"]["url"] == "https://cdn.discordapp.com/avatar.png"
    assert approved["timestamp"].startswith("2026-08-22T12:05:00")
    assert approved["footer"]["text"] == "Yuno • Organização"
    assert approved_fields == {
        "Membro": "<@10>",
        "Nome informado": "Ana Silva",
        "ID informado": "`001`",
        "Aprovado por": "<@20>",
        "Cargo aplicado": "<@&30>",
        "Apelido aplicado": "Ana Silva \\| 001",
    }

    rejected_data = RegistrationLogData.from_payload(
        {
            "decision": "rejected",
            "discord_user_id": "11",
            "submitted_name": "**Bia**",
            "player_id": "002",
            "reviewed_by": "21",
            "reason": "**Dados divergentes** @everyone",
            "decision_at": datetime(2026, 8, 22, 12, 10),
        }
    )
    rejected = renderer.render_rejected(rejected_data).to_dict()
    rejected_fields = {item["name"]: item["value"] for item in rejected["fields"]}

    assert rejected["title"] == "Registro rejeitado"
    assert rejected["color"] == REJECTED_COLOR
    assert rejected["timestamp"].endswith("+00:00")
    assert "thumbnail" not in rejected
    assert rejected_fields["Rejeitado por"] == "<@21>"
    assert rejected_fields["Nome informado"] != "**Bia**"
    assert rejected_fields["Motivo"] != "**Dados divergentes** @everyone"


def test_registration_log_renderer_accepts_legacy_payload_without_exposing_uuid() -> None:
    legacy_id = "123e4567-e89b-12d3-a456-426614174000"
    data = RegistrationLogData.from_payload(
        {"request_id": legacy_id, "decision": "approved"}
    )
    rendered = str(RegistrationLogRenderer().render_approved(data).to_dict())

    assert legacy_id not in rendered
    assert "approved" not in rendered
    assert "Registro aprovado" in rendered


def test_registration_submit_receipt_uses_configured_text_without_uuid() -> None:
    request_id = "123e4567-e89b-12d3-a456-426614174000"

    class SubmitAPI:
        async def registration_submit(
            self, guild_id, registration, *, actor, panel_config_version
        ):
            assert guild_id == 100
            assert registration == {"name": "Ana", "player_id": "001"}
            assert actor.user_id == 10
            assert panel_config_version == 2
            return {"id": request_id}

        async def registration_config(self, guild_id):
            assert guild_id == 100
            return {"data": {"submitted_message": "Recebemos seu registro para análise."}}

    actor = ActorContext(
        guild_id=100,
        user_id=10,
        role_ids=(),
        discord_permissions=(),
        channel_id=1001,
        category_id=None,
        actor_type="user",
        is_guild_owner=False,
        correlation_id="submit-visual",
    )
    interaction = SimpleNamespace(
        data={
            "components": [
                {
                    "components": [
                        {"custom_id": "registration_name", "value": "Ana"},
                        {"custom_id": "registration_player_id", "value": "001"},
                    ]
                }
            ]
        }
    )
    result = asyncio.run(
        registration_ui.submit(
            RoutedContext(
                interaction=interaction,
                actor=actor,
                panel={"config_version": 2},
                api=SubmitAPI(),
                receipt_id="receipt-1",
            )
        )
    )

    assert result.content == "Recebemos seu registro para análise."
    assert request_id not in result.content


def test_registration_delivery_resolves_avatar_and_propagates_optional_destination_failures() -> None:
    class FakeChannel:
        id = 1003

        def __init__(self) -> None:
            self.embed = None

        async def send(self, *, embed, allowed_mentions):
            assert allowed_mentions is not None
            self.embed = embed
            return SimpleNamespace(id=555)

    member = SimpleNamespace(
        display_avatar=SimpleNamespace(url="https://cdn.discordapp.com/member.png")
    )
    guild = SimpleNamespace(get_member=lambda user_id: member if user_id == 10 else None)
    channel = FakeChannel()
    bot = SimpleNamespace(
        get_channel=lambda channel_id: channel if channel_id == 1003 else None,
        fetch_channel=None,
        get_guild=lambda guild_id: guild if guild_id == 100 else None,
        get_user=lambda _user_id: None,
        fetch_user=None,
    )
    item = {
        "guild_id": "100",
        "destination_id": "1003",
        "payload": {
            "decision": "approved",
            "discord_user_id": "10",
            "submitted_name": "Ana",
            "player_id": "001",
            "reviewed_by": "20",
            "member_role_id": "30",
            "target_nickname": "Ana | 001",
            "decision_at": "2026-08-22T12:05:00+00:00",
            "show_member_avatar": True,
        },
    }

    result = asyncio.run(registration_ui.deliver_log(bot, item))
    assert result == "555"
    assert channel.embed.to_dict()["thumbnail"]["url"].endswith("member.png")

    async def missing_channel(_channel_id):
        raise RuntimeError("canal removido")

    missing_bot = SimpleNamespace(
        get_channel=lambda _channel_id: None,
        fetch_channel=missing_channel,
    )
    with pytest.raises(RuntimeError, match="canal removido"):
        asyncio.run(registration_ui.deliver_log(missing_bot, item))


def test_registration_avatar_absence_does_not_fail_and_closed_dm_is_retriable() -> None:
    async def missing_user(_user_id):
        raise RuntimeError("membro indisponível")

    avatar_bot = SimpleNamespace(
        get_guild=lambda _guild_id: None,
        get_user=lambda _user_id: None,
        fetch_user=missing_user,
    )
    assert (
        asyncio.run(
            registration_ui._resolve_avatar_url(
                avatar_bot, guild_id=100, user_id="10"
            )
        )
        is None
    )

    class ClosedDMUser:
        display_avatar = SimpleNamespace(url="https://cdn.discordapp.com/member.png")

        async def send(self, **_kwargs):
            raise RuntimeError("DM fechada")

    dm_bot = SimpleNamespace(
        get_user=lambda user_id: ClosedDMUser() if user_id == 10 else None,
        fetch_user=missing_user,
    )
    with pytest.raises(RuntimeError, match="DM fechada"):
        asyncio.run(
            registration_ui.deliver_dm(
                dm_bot,
                {
                    "destination_id": "10",
                    "payload": {
                        "decision": "rejected",
                        "message": "Seu registro não foi aprovado.",
                        "reason": "Dados divergentes",
                    },
                },
            )
        )


def test_registration_review_delivery_reuses_resource_panel_with_decision_snapshot(
    monkeypatch,
) -> None:
    reconciliations: list[dict] = []
    attachments: list[tuple[int, str, int, int]] = []

    async def reconcile(_self, **kwargs):
        reconciliations.append(kwargs)
        return {"channel_id": "1002", "message_id": "555"}

    class FakeAPI:
        async def registration_request(self, guild_id, request_id):
            assert (guild_id, request_id) == (100, "request-1")
            return {
                "id": request_id,
                "discord_user_id": "10",
                "submitted_name": "Ana",
                "player_id_original": "001",
                "status": "approved",
                "reviewed_by": "20",
                "rejection_reason": None,
                "target_nickname": "Ana | 001",
                "created_at": "2026-08-22T12:00:00+00:00",
                "approved_at": "2026-08-22T12:05:00+00:00",
            }

        async def registration_config(self, guild_id):
            assert guild_id == 100
            return {
                "version": 9,
                "data": {
                    "nickname_template": "{name} | {id}",
                    "member_role_id": "999",
                    "show_member_avatar": True,
                },
            }

        async def registration_attach_review_message(
            self, guild_id, request_id, channel_id, message_id, *, actor
        ):
            assert actor.actor_type == "system"
            attachments.append((guild_id, request_id, channel_id, message_id))

    monkeypatch.setattr(registration_ui.PanelPublisher, "reconcile", reconcile)
    member = SimpleNamespace(
        display_avatar=SimpleNamespace(url="https://cdn.discordapp.com/member.png")
    )
    guild = SimpleNamespace(
        id=100,
        get_member=lambda user_id: member if user_id == 10 else None,
    )
    api = FakeAPI()
    bot = SimpleNamespace(
        user=SimpleNamespace(id=900),
        platform_api=api,
        get_guild=lambda guild_id: guild if guild_id == 100 else None,
        get_user=lambda _user_id: None,
        fetch_user=None,
    )
    item = {
        "guild_id": "100",
        "resource_id": "request-1",
        "destination_id": "1002",
        "correlation_id": "decision-1",
        "payload": {
            "decision": "approved",
            "config_version": 3,
            "member_role_id": "30",
            "decision_at": "2026-08-22T12:05:00+00:00",
            "show_member_avatar": True,
        },
    }

    assert asyncio.run(registration_ui.deliver_review(bot, item)) == "555"
    assert asyncio.run(registration_ui.deliver_review(bot, item)) == "555"
    assert len(reconciliations) == 2
    assert all(call["resource_id"] == "request-1" for call in reconciliations)
    assert all(call["panel_key"] == "review" for call in reconciliations)
    context = reconciliations[0]["render_context"]
    assert context["config_version"] == 3
    assert context["member_role_id"] == "30"
    assert context["target_nickname"] == "Ana | 001"
    assert context["avatar_url"].endswith("member.png")
    assert attachments == [
        (100, "request-1", 1002, 555),
        (100, "request-1", 1002, 555),
    ]


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


def test_registration_admin_uses_six_clear_configuration_steps() -> None:
    selector = registration_ui._section_select()
    options = selector["options"]

    assert [item["value"] for item in options] == [
        "channels",
        "team",
        "rules",
        "panel",
        "messages",
        "notifications",
    ]
    assert [item["label"] for item in options] == [
        "1 · Canais",
        "2 · Equipe e cargo",
        "3 · Regras do formulário",
        "4 · Aparência do painel",
        "5 · Mensagens",
        "6 · Logs e avisos",
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
    asyncio.run(
        registration_ui.set_log_avatar(
            SimpleNamespace(data={"values": ["hide"]}), object()
        )
    )

    assert saved == [
        {"player_id_numeric_only": False},
        {"allow_resubmit_after_rejection": False},
        {"show_member_avatar": False},
    ]
    assert rendered == ["rules", "rules", "notifications"]


def test_registration_notification_settings_are_explicit_and_keep_semantic_colors() -> None:
    fields = registration_ui.CONFIG_MODAL_FIELDS["notifications"]
    assert [item[0] for item in fields] == [
        "log_approved_title",
        "log_rejected_title",
        "log_footer",
        "approved_dm_title",
        "rejected_dm_title",
    ]
    assert APPROVED_COLOR == 0x57F287
    assert REJECTED_COLOR == 0xED4245


def test_registration_notification_section_supports_drafts_from_previous_version(
    monkeypatch,
) -> None:
    captured: dict = {}

    async def admin_state(_api, _guild_id):
        return (
            {"lifecycle": "active"},
            {
                "base_published_version": 2,
                "data": {},
            },
        )

    async def replace(_interaction, data, **_kwargs):
        captured.update(data)

    monkeypatch.setattr(registration_ui, "_admin_state", admin_state)
    monkeypatch.setattr(registration_ui, "_replace_central", replace)

    asyncio.run(
        registration_ui._render_section(
            SimpleNamespace(guild_id=100), object(), "notifications"
        )
    )

    rendered = str(captured)
    assert "Registro aprovado" in rendered
    assert "Registro rejeitado" in rendered
    assert "Yuno • Sistema de Registro" in rendered
    assert "Mostrar foto do membro" in rendered


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
    navigation = next(
        item for item in children if item["type"] == 1 and item["components"][0]["type"] == 3
    )
    action = next(
        item for item in children if item["type"] == 1 and item["components"][0]["type"] == 2
    )
    button_data = action["components"][0]
    assert navigation["components"][0]["custom_id"] == "yuno:central:v1:core:select_module"
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
