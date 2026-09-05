import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "bot"))

from app.domain_modules.adv.domain import (  # noqa: E402
    AdvDomainError,
    normalize_discord_id,
    normalize_optional_reason,
    normalize_reason,
)
from app.domain_modules.adv.schemas import AdvConfig  # noqa: E402
from yuno_bot.domain_modules.adv.renderers import AdvLogData, AdvRenderer  # noqa: E402
from yuno_bot.domain_modules.adv.ui import render_public  # noqa: E402


def test_normalize_reason_requires_non_empty() -> None:
    with pytest.raises(AdvDomainError, match="obrigatório"):
        normalize_reason("")
    with pytest.raises(AdvDomainError, match="obrigatório"):
        normalize_reason("   ")
    assert normalize_reason("  spawn de arma proibida  ") == "spawn de arma proibida"


def test_normalize_reason_enforces_300_chars() -> None:
    with pytest.raises(AdvDomainError, match="300"):
        normalize_reason("a" * 301)
    assert normalize_reason("a" * 300) == "a" * 300


def test_normalize_optional_reason_allows_none_and_blank() -> None:
    assert normalize_optional_reason(None) is None
    assert normalize_optional_reason("   ") is None
    assert normalize_optional_reason("  engano  ") == "engano"


def test_normalize_optional_reason_enforces_300_chars() -> None:
    with pytest.raises(AdvDomainError, match="300"):
        normalize_optional_reason("a" * 301)


def test_normalize_discord_id_accepts_raw_and_mention() -> None:
    assert normalize_discord_id("123456789012345678") == "123456789012345678"
    assert normalize_discord_id("<@123456789012345678>") == "123456789012345678"
    assert normalize_discord_id("<@!123456789012345678>") == "123456789012345678"


def test_normalize_discord_id_rejects_non_numeric() -> None:
    with pytest.raises(AdvDomainError, match="válido"):
        normalize_discord_id("nao-e-um-id")


def test_adv_config_defaults() -> None:
    config = AdvConfig()
    assert config.enabled is True
    assert config.staff_role_ids == []
    assert config.panel_channel_id == ""
    with pytest.raises(Exception):
        AdvConfig.model_validate({"unknown": True})


def test_render_public_contains_button_and_title() -> None:
    config = AdvConfig().model_dump(mode="json")
    result = asyncio.run(render_public({"config": config})).data
    text = str(result)
    assert "yuno:v1:adv:staff:open_form" in text
    assert config["button_label"] in text
    assert config["panel_title"] in text


def test_adv_renderer_applied() -> None:
    data = AdvLogData.from_payload(
        {
            "discord_user_id": "10",
            "member_display_name": "Ana",
            "moderator_id": "20",
            "moderator_display_name": "Staff",
            "reason": "spawn de arma proibida",
            "created_at": "2026-01-01T00:00:00+00:00",
            "kind": "applied",
        }
    )
    embed = AdvRenderer().render(data)
    assert embed.color is not None
    field_names = [field.name for field in embed.fields]
    assert "🛡️ Responsável" in field_names
    assert any("spawn de arma proibida" in str(field.value) for field in embed.fields)


def test_adv_renderer_revoked() -> None:
    data = AdvLogData.from_payload(
        {
            "discord_user_id": "10",
            "moderator_id": "30",
            "reason": "aplicada por engano",
            "kind": "revoked",
            "log_title": "Advertência revogada",
        }
    )
    embed = AdvRenderer().render(data)
    assert embed.title == "Advertência revogada"
    field_names = [field.name for field in embed.fields]
    assert "🛡️ Revogado por" in field_names
