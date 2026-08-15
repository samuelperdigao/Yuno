import pytest

from yuno_bot import dashboard
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
    assert list(dashboard.dashboard_specs()) == ["registration"]


def test_dashboard_message_ref_and_with_dashboard_ref_roundtrip() -> None:
    config = {"settings": {"preserved": {"value": True}}}
    updated = dashboard.with_dashboard_ref(config, channel_id=10, message_id=20)

    assert dashboard.dashboard_message_ref(updated) == (10, 20)
    assert updated["settings"]["preserved"] == {"value": True}


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
        assert kwargs == {"ephemeral": True, "thinking": True}
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
