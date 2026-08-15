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
