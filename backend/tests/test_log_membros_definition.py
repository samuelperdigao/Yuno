import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.domain_modules.log_membros.definition import (  # noqa: E402
    LOG_MEMBROS_CONFIGURATION,
    MODULE_DEFINITION,
)
from app.platform.registry import ModuleRegistry  # noqa: E402


def test_manifest_shape() -> None:
    manifest = MODULE_DEFINITION.manifest
    assert manifest.key == "log_membros"
    assert manifest.runtime_modes == ("domain",)
    assert manifest.default_runtime_mode == "domain"
    assert MODULE_DEFINITION.lifecycle.requires_published_configuration is True
    assert {item.key for item in MODULE_DEFINITION.capabilities} == {"log_membros.configure"}


def test_registers_cleanly_without_dependencies() -> None:
    registry = ModuleRegistry()
    registry.register(MODULE_DEFINITION)
    assert registry.get("log_membros") is MODULE_DEFINITION
    manifest_entry = registry.manifests()[0]
    assert manifest_entry["key"] == "log_membros"
    assert manifest_entry["configuration"]["schema_version"] == 1


def test_required_channels_must_be_present() -> None:
    errors = LOG_MEMBROS_CONFIGURATION.validate({})
    assert any("join_channel_id" in error for error in errors)
    assert any("leave_channel_id" in error for error in errors)


def test_optional_fields_may_be_omitted() -> None:
    errors = LOG_MEMBROS_CONFIGURATION.validate(
        {"join_channel_id": "100", "leave_channel_id": "200"}
    )
    assert errors == []


def test_join_role_ids_must_be_a_list_of_strings() -> None:
    errors = LOG_MEMBROS_CONFIGURATION.validate(
        {
            "join_channel_id": "100",
            "leave_channel_id": "200",
            "join_role_ids": "300",
        }
    )
    assert any("join_role_ids" in error for error in errors)


def test_leave_extra_message_respects_max_length() -> None:
    errors = LOG_MEMBROS_CONFIGURATION.validate(
        {
            "join_channel_id": "100",
            "leave_channel_id": "200",
            "leave_extra_message": "x" * 501,
        }
    )
    assert any("leave_extra_message" in error for error in errors)


def test_unknown_field_is_rejected() -> None:
    errors = LOG_MEMBROS_CONFIGURATION.validate(
        {
            "join_channel_id": "100",
            "leave_channel_id": "200",
            "not_a_real_field": True,
        }
    )
    assert any("not_a_real_field" in error for error in errors)
