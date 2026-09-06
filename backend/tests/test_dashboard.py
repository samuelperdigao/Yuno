from types import SimpleNamespace

import pytest
from yuno_bot import dashboard
from yuno_bot.domain_modules.tags import ui as tags_ui
from yuno_bot.modules import discover_modules
from yuno_bot.platform.components_v2 import string_select
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


def test_home_is_a_summary_and_does_not_render_the_module_catalog() -> None:
    data = dashboard.build_payload({}, control_states=ACTIVE_STATES)
    content = "\n".join(
        component.get("content", "")
        for component in data["components"][0]["components"]
    )

    assert data["allowed_mentions"] == {"parse": [], "replied_user": False}
    assert "YUNO / Visão geral" in content
    assert "Módulos disponíveis" in content
    assert "Ativos" in content
    assert "Configuração pendente" in content
    assert "parceria:open" not in str(data)
    assert dashboard.route_custom_id("core", "modules") in str(data)


def test_modules_screen_scales_with_groups_without_truncating_options(monkeypatch) -> None:
    specs = {
        f"module_{index}": dashboard.DomainDashboardSpec(
            key=f"module_{index}",
            nome=f"Módulo {index}",
            icon="",
            ordem=index,
        )
        for index in range(26)
    }
    monkeypatch.setattr(dashboard, "dashboard_specs", lambda: specs)

    first = dashboard.build_modules_payload({}, page=0)
    second = dashboard.build_modules_payload({}, page=1)
    first_select = next(
        item
        for item in first["components"][0]["components"]
        if item["type"] == 1 and item["components"][0]["type"] == 3
    )["components"][0]
    second_select = next(
        item
        for item in second["components"][0]["components"]
        if item["type"] == 1 and item["components"][0]["type"] == 3
    )["components"][0]

    assert len(first_select["options"]) == 25
    assert len(second_select["options"]) == 1
    assert first_select["options"][0]["value"] == "module_0"
    assert second_select["options"][0]["value"] == "module_25"
    assert dashboard.central_custom_id("core", "group_1") in str(first)
    assert dashboard.central_custom_id("core", "group_0") in str(second)


def test_navigation_row_keeps_disabled_buttons_with_unique_custom_ids() -> None:
    data = dashboard.build_modules_payload({})
    custom_ids = []

    def collect_components(component):
        if isinstance(component, dict):
            if "custom_id" in component:
                custom_ids.append(component["custom_id"])
            for child in component.get("components", []):
                collect_components(child)
        elif isinstance(component, list):
            for child in component:
                collect_components(child)

    collect_components(data)

    assert len(custom_ids) == len(set(custom_ids))


def test_modules_screen_shows_selected_summary_and_only_its_open_action() -> None:
    data = dashboard.build_modules_payload(
        {}, selected_module="meta", control_states=ACTIVE_STATES
    )
    serialized = str(data)

    assert "Meta" in serialized
    assert dashboard.central_custom_id("meta", "open") in serialized
    assert "registration:open" not in serialized


def test_string_select_rejects_more_than_discord_allows() -> None:
    options = [{"label": str(index), "value": str(index)} for index in range(26)]

    with pytest.raises(ValueError, match="no máximo 25"):
        string_select(custom_id="central", options=options, placeholder="Escolha")


def test_inactive_license_keeps_home_readable() -> None:
    data = dashboard.build_payload(
        {}, control_states=ACTIVE_STATES, license_active=False
    )

    assert data["components"][0]["accent_color"] == uk.DANGER
    assert "Licença inativa" in str(data)


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
        "registration", "tags", "farm_tickets", "meta", "parceria"
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
        "parceria",
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
    assert dashboard.route_custom_id("core", "modules") in str(edited[0][3])
    assert "estados dos módulos" in str(edited[0][3])


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
async def test_raw_v2_module_select_routes_to_the_selected_module(monkeypatch) -> None:
    interaction = _FakeInteraction(
        "yuno:central:v1:core:select_module",
        component_type=3,
        values=["registration"],
    )
    called = []

    async def dispatch_page(current, module_key):
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
        called.append(module_key)

    monkeypatch.setattr(dashboard, "_dispatch_page", dispatch_page)

    assert await dashboard.dispatch_components_v2(interaction) is True
    assert called == ["meta"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("custom_id", "component_type", "values"),
    [
        ("yuno:central:v1:core:select_module", 3, ["meta"]),
        ("yuno:central:v1:meta:open", 2, None),
    ],
    ids=["select", "botao"],
)
async def test_pagina_de_modulo_e_reconhecida_antes_de_qualquer_chamada_de_api(
    monkeypatch, custom_id, component_type, values
) -> None:
    """O Discord da 3 segundos; I/O antes do defer gasta esse orcamento.

    O botao de cada linha da Central chegava em `_dispatch_page` sem defer
    nenhum e a pagina do modulo so adiava depois de buscar dados. Em producao
    isso virou `discord.NotFound 404 (10062): Unknown interaction` -- para o
    usuario, "o bot nao respondeu". O select ja estava correto; este teste
    cobra os dois pelo mesmo criterio.
    """

    interaction = _FakeInteraction(custom_id, component_type=component_type, values=values)
    deferido_antes_da_api = []

    async def central_config(current):
        deferido_antes_da_api.append(current.response.is_done())
        return None  # corta o fluxo: o que importa ja foi observado

    monkeypatch.setattr(dashboard, "_central_config", central_config)

    assert await dashboard.dispatch_components_v2(interaction) is True
    assert deferido_antes_da_api == [True]


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
        # Toda interacao real tem `response`, e `_dispatch_page` reconhece a
        # interacao antes de qualquer I/O.
        response=_FakeResponse(),
    )
    await dashboard._dispatch_page(interaction, dashboard.CENTRAL_HOME_VALUE)

    assert interaction.response.is_done()

    assert edited[0][:2] == (10, 20)
    assert "Central operacional" in str(edited[0][2])


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


@pytest.mark.asyncio
async def test_visual_routes_follow_the_pilot_flow_without_calling_business_actions(
    monkeypatch,
) -> None:
    called = []

    async def central_config(current):
        return {"settings": {}}

    async def render_home(current, config):
        called.append(("home", config))

    async def render_modules(current, config, **kwargs):
        called.append(("modules", config, kwargs))

    async def dispatch_page(current, module_key):
        called.append(("page", module_key))

    async def dispatch_action(current, module_key, action_key):
        called.append(("action", module_key, action_key))

    monkeypatch.setattr(dashboard, "_central_config", central_config)
    monkeypatch.setattr(dashboard, "_render_home", render_home)
    monkeypatch.setattr(dashboard, "_render_modules", render_modules)
    monkeypatch.setattr(dashboard, "_dispatch_page", dispatch_page)
    monkeypatch.setattr(dashboard, "_dispatch_action", dispatch_action)

    for custom_id in (
        dashboard.route_custom_id("core", "modules"),
        dashboard.route_custom_id("parceria", "overview"),
        dashboard.route_custom_id("parceria", "configuration"),
        dashboard.route_custom_id("parceria", "diagnostic"),
    ):
        interaction = _FakeInteraction(custom_id, component_type=2)
        assert await dashboard.dispatch_components_v2(interaction) is True

    assert [item[0] for item in called] == ["modules", "page", "action", "action"]
    assert called[1] == ("page", "parceria")
    assert called[2:] == [
        ("action", "parceria", "open_system"),
        ("action", "parceria", "diagnose"),
    ]


@pytest.mark.asyncio
async def test_invalid_visual_route_is_rejected_without_business_dispatch(monkeypatch) -> None:
    invalid = []

    async def central_config(current):
        return {"settings": {}}

    async def render_invalid(current):
        invalid.append(current)

    monkeypatch.setattr(dashboard, "_central_config", central_config)
    monkeypatch.setattr(dashboard, "_render_invalid_route", render_invalid)
    interaction = _FakeInteraction(
        dashboard.route_custom_id("parceria", "not_a_route"), component_type=2
    )

    assert await dashboard.dispatch_components_v2(interaction) is True
    assert invalid == [interaction]
