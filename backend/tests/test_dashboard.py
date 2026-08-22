import pytest
from types import SimpleNamespace

from yuno_bot import dashboard
from yuno_bot.domain_modules.tags import ui as tags_ui
from yuno_bot.modules import discover_modules


def _text_content(payload: dict) -> str:
    return payload["components"][0]["components"][0]["content"]


def test_central_uses_a_module_selector_with_stable_custom_id() -> None:
    payload = dashboard.build_payload({})
    content = _text_content(payload)
    select = payload["components"][0]["components"][1]["components"][0]
    options = {item["value"]: item["label"] for item in select["options"]}

    for spec in dashboard.dashboard_specs().values():
        assert options[spec.key] == spec.nome

    assert select["custom_id"] == "yuno:central:v1:core:select_module"
    assert payload["allowed_mentions"] == {"parse": [], "replied_user": False}
    assert "Selecione um modulo" in content
    assert "set" not in options


def test_legacy_catalog_has_no_runtime_implementation() -> None:
    modules = discover_modules(force=True)

    assert len(modules) == 16
    for spec in modules.values():
        assert spec.cogs == ()
        assert spec.views == ()
        assert spec.setup_channels == ()
        assert spec.dashboard_fields == ()
        assert spec.control_plane is None
        assert spec.retired is True
    assert list(dashboard.dashboard_specs()) == ["registration", "tags", "meta"]


def test_module_navigation_switches_between_released_modules() -> None:
    navigation = dashboard.module_navigation("registration")
    select = navigation["components"][0]
    options = {item["value"]: item for item in select["options"]}

    assert select["custom_id"] == "yuno:central:v1:core:select_module"
    assert select["placeholder"] == "Trocar de modulo"
    assert options["registration"]["default"] is True
    assert options["tags"]["default"] is False
    assert options["meta"]["default"] is False
    assert set(options) == {"registration", "tags", "meta"}


def test_tags_primary_screen_keeps_only_the_simple_daily_flow() -> None:
    data = tags_ui._detail_payload(
        draft={
            "bindings": [{"discord_role_id": "10", "tag": "[MEM]", "enabled": True}],
            "base_published_version": 1,
        },
        lifecycle="active",
        last_run={},
        lines=["<@&10> → `[MEM]` · ativo"],
        current_page=0,
        max_page=0,
    )
    rows = [
        component["components"]
        for component in data["components"][0]["components"]
        if component["type"] == 1
    ]
    buttons = {
        item["custom_id"].rsplit(":", 1)[-1]: item
        for row in rows
        for item in row
        if item["type"] == 2
    }

    assert set(buttons) == {
        "add_binding",
        "manage_binding",
        "confirm_publish",
        "cleanup",
        "preview",
        "advanced",
    }
    assert buttons["confirm_publish"]["label"] == "Confirmar e aplicar"
    assert buttons["cleanup"]["label"] == "Limpar todas as Tags"
    assert "page_prev" not in buttons
    assert "toggle_lifecycle" not in buttons


@pytest.mark.asyncio
async def test_tags_confirm_publishes_activates_and_reconciles_everyone(monkeypatch) -> None:
    calls = []

    class API:
        async def tags_draft_bindings(self, guild_id):
            return {"revision": 4, "base_published_version": 2, "bindings": []}

        async def publish_configuration(self, guild_id, module_key, data, *, actor):
            calls.append(("publish", data))

        async def module_instance(self, guild_id, module_key):
            return {"lifecycle": "inactive", "published_config_version_id": 3}

        async def update_lifecycle(self, guild_id, module_key, **kwargs):
            calls.append(("activate", kwargs))

        async def tags_create_run(self, guild_id, data, *, actor):
            calls.append(("run", data))
            return {"id": "run-1"}

    class Response:
        async def defer(self):
            return None

    sent = []

    class Followup:
        async def send(self, message, **kwargs):
            sent.append(message)

    interaction = SimpleNamespace(
        guild_id=100,
        guild=SimpleNamespace(
            me=SimpleNamespace(guild_permissions=SimpleNamespace(manage_nicknames=True))
        ),
        response=Response(),
        followup=Followup(),
    )
    actor = SimpleNamespace(user_id=900)
    monkeypatch.setattr(tags_ui, "actor_from", lambda current: actor)

    async def no_render(*args, **kwargs):
        return None

    monkeypatch.setattr(tags_ui, "_render_detail", no_render)
    await tags_ui.confirm_publish(interaction, API())

    assert [name for name, _ in calls] == ["publish", "activate", "run"]
    assert calls[-1][1] == {
        "mode": "effective",
        "reason": "confirm_apply",
        "supersede_active": True,
    }
    assert "Tudo confirmado" in sent[-1]


@pytest.mark.asyncio
async def test_tags_cleanup_supersedes_an_active_application(monkeypatch) -> None:
    payloads = []

    class API:
        async def module_instance(self, guild_id, module_key):
            return {"lifecycle": "active", "published_config_version_id": 3}

        async def tags_create_run(self, guild_id, data, *, actor):
            payloads.append(data)
            return {"id": "cleanup-1"}

    class Response:
        async def defer(self):
            return None

    sent = []

    class Followup:
        async def send(self, message, **kwargs):
            sent.append(message)

    interaction = SimpleNamespace(
        guild_id=100,
        response=Response(),
        followup=Followup(),
    )
    monkeypatch.setattr(tags_ui, "actor_from", lambda current: SimpleNamespace(user_id=900))

    async def no_render(*args, **kwargs):
        return None

    monkeypatch.setattr(tags_ui, "_render_detail", no_render)
    await tags_ui.confirm_cleanup(interaction, API())

    assert payloads == [
        {"mode": "base_only", "reason": "cleanup", "supersede_active": True}
    ]
    assert "desativado automaticamente" in sent[-1]


def test_dashboard_message_ref_and_with_dashboard_ref_roundtrip() -> None:
    config = {"settings": {"preserved": {"value": True}}}
    updated = dashboard.with_dashboard_ref(config, channel_id=10, message_id=20)

    assert dashboard.dashboard_message_ref(updated) == (10, 20)
    assert updated["settings"]["preserved"] == {"value": True}


@pytest.mark.asyncio
async def test_startup_refresh_updates_only_the_registered_central(monkeypatch) -> None:
    edited = []

    class Channel:
        id = 10

        async def fetch_message(self, message_id):
            assert message_id == 20
            return SimpleNamespace(author=SimpleNamespace(id=42))

    class Guild:
        me = SimpleNamespace(id=42)

        def get_channel(self, channel_id):
            return Channel() if channel_id == 10 else None

    async def edit(bot, channel_id, message_id, data):
        edited.append((bot, channel_id, message_id, data))

    monkeypatch.setattr(dashboard, "_edit_v2", edit)
    bot = object()
    refreshed = await dashboard.refresh_existing(
        bot,
        Guild(),
        {"settings": {"dashboard": {"panel_channel_id": "10", "panel_message_id": "20"}}},
    )

    assert refreshed is True
    assert edited[0][1:3] == (10, 20)
    options = edited[0][3]["components"][0]["components"][1]["components"][0]["options"]
    assert {item["value"] for item in options} == {"registration", "tags", "meta"}


def test_central_dynamic_patterns_do_not_compete_for_string_selects() -> None:
    root = "yuno:central:v1:core:select_module"
    section = "yuno:central:v1:registration:section"
    assert dashboard.CENTRAL_MODULE_SELECT_PATTERN.fullmatch(root)
    assert not dashboard.CENTRAL_ACTION_PATTERN.fullmatch(root)
    assert dashboard.CENTRAL_ACTION_PATTERN.fullmatch(section)
    assert not dashboard.CENTRAL_MODULE_SELECT_PATTERN.fullmatch(section)


class _FakeResponse:
    def __init__(self) -> None:
        self.deferred = False

    def is_done(self) -> bool:
        return self.deferred

    async def defer(self, **kwargs) -> None:
        assert kwargs == {}
        self.deferred = True


class _FakeInteraction:
    def __init__(self, custom_id: str, *, component_type: int, values=None) -> None:
        self.data = {
            "custom_id": custom_id,
            "component_type": component_type,
            "values": values or [],
        }
        self.response = _FakeResponse()


@pytest.mark.asyncio
async def test_raw_v2_module_select_is_acknowledged_before_dispatch(monkeypatch) -> None:
    interaction = _FakeInteraction(
        "yuno:central:v1:core:select_module",
        component_type=3,
        values=["registration"],
    )
    called = []

    async def dispatch_page(current, module_key):
        assert current.response.is_done()
        called.append(module_key)

    monkeypatch.setattr(dashboard, "_dispatch_page", dispatch_page)

    handled = await dashboard.dispatch_components_v2(interaction)

    assert handled is True
    assert called == ["registration"]


@pytest.mark.asyncio
async def test_raw_v2_action_select_is_acknowledged_before_dispatch(monkeypatch) -> None:
    interaction = _FakeInteraction(
        "yuno:central:v1:registration:section",
        component_type=3,
        values=["system"],
    )

    async def dispatch_action(current, module_key, action_key):
        assert current.response.is_done()
        assert (module_key, action_key) == ("registration", "section")

    monkeypatch.setattr(dashboard, "_dispatch_action", dispatch_action)

    assert await dashboard.dispatch_components_v2(interaction) is True
