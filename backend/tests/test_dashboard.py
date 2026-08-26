from types import SimpleNamespace

import pytest
from yuno_bot import dashboard
from yuno_bot.domain_modules.tags import ui as tags_ui
from yuno_bot.modules import discover_modules
from yuno_bot.platform import ui_kit as uk

SECTION = 9

ACTIVE_STATES = {
    "registration": {"lifecycle": "active", "published_config_version_id": "7"},
    "tags": {"lifecycle": "active"},
    "farm_tickets": {"lifecycle": "inactive", "published_config_version_id": "3"},
    "meta": {"lifecycle": "inactive"},
}


def _text_content(payload: dict) -> str:
    return payload["components"][0]["components"][0]["content"]


def _rows(payload: dict) -> dict[str, dict]:
    """Linhas da Central indexadas pelo módulo que o botão abre."""

    return {
        item["accessory"]["custom_id"].split(":")[-2]: item
        for item in payload["components"][0]["components"]
        if item["type"] == SECTION
    }


def _row_text(row: dict) -> str:
    return row["components"][0]["content"]


def test_central_lists_one_row_per_module_with_a_stable_open_button() -> None:
    payload = dashboard.build_payload({})
    rows = _rows(payload)
    specs = dashboard.dashboard_specs()

    assert list(rows) == list(specs)
    for key, spec in specs.items():
        assert spec.nome in _row_text(rows[key])
        assert spec.descricao in _row_text(rows[key])
        assert rows[key]["accessory"]["custom_id"] == f"yuno:central:v1:{key}:open"

    assert payload["allowed_mentions"] == {"parse": [], "replied_user": False}
    assert "Selecione um módulo" in _text_content(payload)
    assert "set" not in rows


def test_central_row_translates_lifecycle_into_status_and_next_step() -> None:
    payload = dashboard.build_payload({}, control_states=ACTIVE_STATES)
    rows = _rows(payload)
    labels = {key: row["accessory"]["label"] for key, row in rows.items()}
    styles = {key: row["accessory"]["style"] for key, row in rows.items()}

    assert "No ar" in _row_text(rows["registration"])
    assert labels["registration"] == "Gerenciar"
    assert styles["registration"] == 2

    # `active` sem configuração publicada é rascunho, não módulo no ar.
    assert "Aguardando publicação" in _row_text(rows["tags"])
    assert labels["tags"] == "Revisar e publicar"
    assert styles["tags"] == 1

    assert "Desligado" in _row_text(rows["farm_tickets"])
    assert labels["farm_tickets"] == "Reativar"
    assert "Não configurado" in _row_text(rows["meta"])
    assert labels["meta"] == "Configurar"

    assert "**No ar** 1" in _text_content(payload)


def test_central_row_announces_the_plan_a_module_requires() -> None:
    rows = _rows(dashboard.build_payload({}, control_states=ACTIVE_STATES))

    assert "Requer o plano Pro" in _row_text(rows["farm_tickets"])
    assert "Requer o plano" not in _row_text(rows["registration"])


def test_inactive_license_keeps_the_list_readable_and_blocks_every_button() -> None:
    payload = dashboard.build_payload(
        {}, control_states=ACTIVE_STATES, license_active=False
    )
    rows = _rows(payload)

    assert payload["components"][0]["accent_color"] == uk.DANGER
    assert "Licença inativa" in _text_content(payload)
    assert list(rows) == list(dashboard.dashboard_specs())
    assert all(row["accessory"]["disabled"] for row in rows.values())


def test_legacy_catalog_has_no_runtime_implementation() -> None:
    modules = discover_modules(force=True)

    assert len(modules) == 15
    for spec in modules.values():
        assert spec.cogs == ()
        assert spec.views == ()
        assert spec.setup_channels == ()
        assert spec.dashboard_fields == ()
        assert spec.control_plane is None
        assert spec.retired is True
    assert list(dashboard.dashboard_specs()) == [
        "registration", "tags", "farm_tickets", "meta"
    ]


def test_module_navigation_switches_between_released_modules() -> None:
    navigation = dashboard.module_navigation("registration")
    select = navigation["components"][0]
    options = {item["value"]: item for item in select["options"]}

    assert select["custom_id"] == "yuno:central:v1:core:select_module"
    assert select["placeholder"] == "Trocar de módulo"
    assert options["registration"]["default"] is True
    assert options["tags"]["default"] is False
    assert options["meta"]["default"] is False
    assert set(options) == {
        dashboard.CENTRAL_HOME_VALUE,
        "registration",
        "tags",
        "farm_tickets",
        "meta",
    }


def test_module_navigation_opens_with_the_way_back_to_the_central() -> None:
    options = dashboard.module_navigation("tags")["components"][0]["options"]

    # Primeira opção: a página do módulo substitui a mensagem da Central, então
    # sem esta entrada só se sai de um módulo entrando em outro.
    assert options[0]["value"] == dashboard.CENTRAL_HOME_VALUE
    assert options[0]["default"] is False


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
    assert set(_rows(edited[0][3])) == {
        "registration", "tags", "farm_tickets", "meta"
    }


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
async def test_open_button_routes_to_the_module_page(monkeypatch) -> None:
    interaction = _FakeInteraction("yuno:central:v1:meta:open", component_type=2)
    called = []

    async def dispatch_page(current, module_key):
        # Botão não é seleção: quem defere é a própria página do módulo.
        assert not current.response.is_done()
        called.append(module_key)

    monkeypatch.setattr(dashboard, "_dispatch_page", dispatch_page)

    assert await dashboard.dispatch_components_v2(interaction) is True
    assert called == ["meta"]


@pytest.mark.asyncio
async def test_module_keeps_its_own_open_action_when_it_declares_one(monkeypatch) -> None:
    interaction = _FakeInteraction("yuno:central:v1:meta:open", component_type=2)
    handled = []

    monkeypatch.setattr(
        dashboard.ui_registry,
        "admin_action",
        lambda module_key, action_key: SimpleNamespace(key=action_key),
    )

    async def dispatch_action(current, module_key, action_key):
        handled.append((module_key, action_key))

    monkeypatch.setattr(dashboard, "_dispatch_action", dispatch_action)

    assert await dashboard.dispatch_components_v2(interaction) is True
    assert handled == [("meta", "open")]


@pytest.mark.asyncio
async def test_navigation_home_rewrites_the_central_message(monkeypatch) -> None:
    edited = []

    async def central_config(current):
        return {"settings": {}}

    async def states(api, guild_id, actor_id, *, platform_api=None):
        return {"meta": {"lifecycle": "active", "published_config_version_id": "1"}}

    async def edit(bot, channel_id, message_id, data):
        edited.append((channel_id, message_id, data))

    monkeypatch.setattr(dashboard, "_central_config", central_config)
    monkeypatch.setattr(dashboard, "fetch_control_states", states)
    monkeypatch.setattr(dashboard, "_edit_v2", edit)

    interaction = SimpleNamespace(
        client=SimpleNamespace(api=object(), platform_api=object()),
        channel_id=10,
        guild_id=100,
        message=SimpleNamespace(id=20),
        user=SimpleNamespace(id=900),
    )
    await dashboard._dispatch_page(interaction, dashboard.CENTRAL_HOME_VALUE)

    assert edited[0][:2] == (10, 20)
    assert "No ar" in _row_text(_rows(edited[0][2])["meta"])


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
