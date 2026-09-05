import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "bot"))

from app.domain_modules.ausencia.domain import (  # noqa: E402
    AusenciaDomainError,
    compute_window,
    is_near_limit,
    normalize_reason,
    validate_days,
)
from app.domain_modules.ausencia.schemas import AusenciaConfig  # noqa: E402
from yuno_bot.domain_modules.ausencia.renderers import (  # noqa: E402
    AusenciaLogData,
    AusenciaRenderer,
)
from yuno_bot.domain_modules.ausencia.ui import render_public  # noqa: E402


def test_validate_days_accepts_within_bounds() -> None:
    assert validate_days(1, max_days=7) == 1
    assert validate_days(7, max_days=7) == 7


def test_validate_days_rejects_non_integer() -> None:
    with pytest.raises(AusenciaDomainError, match="inteiro"):
        validate_days(True, max_days=7)  # bool e subclasse de int
    with pytest.raises(AusenciaDomainError, match="inteiro"):
        validate_days("3", max_days=7)  # type: ignore[arg-type]


def test_validate_days_rejects_below_one() -> None:
    with pytest.raises(AusenciaDomainError, match="pelo menos 1"):
        validate_days(0, max_days=7)
    with pytest.raises(AusenciaDomainError, match="pelo menos 1"):
        validate_days(-2, max_days=7)


def test_validate_days_above_max_mentions_pd_automatico() -> None:
    with pytest.raises(AusenciaDomainError, match="PD autom"):
        validate_days(8, max_days=7)


def test_normalize_reason_trims_and_allows_empty() -> None:
    assert normalize_reason(None) is None
    assert normalize_reason("   ") is None
    assert normalize_reason("  viagem em familia  ") == "viagem em familia"


def test_normalize_reason_enforces_300_chars() -> None:
    with pytest.raises(AusenciaDomainError, match="300"):
        normalize_reason("a" * 301)
    assert normalize_reason("a" * 300) == "a" * 300


@pytest.mark.parametrize(
    "days,expected", [(1, False), (2, False), (3, False), (4, True), (7, True)]
)
def test_is_near_limit_threshold_is_three_days(days: int, expected: bool) -> None:
    assert is_near_limit(days) is expected


def test_compute_window_requires_timezone_aware_now() -> None:
    with pytest.raises(AusenciaDomainError, match="timezone"):
        compute_window(2, now=datetime(2026, 1, 1))


def test_compute_window_adds_days_to_now() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    started, ends = compute_window(3, now=now)
    assert started == now
    assert ends == now + timedelta(days=3)


def test_ausencia_config_defaults() -> None:
    config = AusenciaConfig()
    assert config.enabled is True
    assert config.max_dias == 7
    assert config.panel_channel_id == ""
    with pytest.raises(Exception):
        AusenciaConfig.model_validate({"unknown": True})


def test_render_public_contains_button_and_title() -> None:
    config = AusenciaConfig().model_dump(mode="json")
    result = asyncio.run(render_public({"config": config})).data
    text = str(result)
    assert "yuno:v1:ausencia:public:open_form" in text
    assert config["button_label"] in text
    assert config["panel_title"] in text


def test_ausencia_renderer_marks_near_limit() -> None:
    data = AusenciaLogData.from_payload(
        {
            "discord_user_id": "10",
            "member_display_name": "Ana",
            "days": 5,
            "reason": "viagem",
            "started_at": "2026-01-01T00:00:00+00:00",
            "ends_at": "2026-01-06T00:00:00+00:00",
            "near_limit": True,
        }
    )
    embed = AusenciaRenderer().render_registered(data)
    assert embed.color is not None
    field_names = [field.name for field in embed.fields]
    assert "⚠️ Atenção" in field_names
    assert any("viagem" in str(field.value) for field in embed.fields)


def test_ausencia_renderer_overdue_reminder() -> None:
    data = AusenciaLogData.from_payload(
        {
            "discord_user_id": "10",
            "ends_at": "2026-01-06T00:00:00+00:00",
            "reminder_title": "Sua ausência venceu",
            "reminder_message": "Renove ou pode virar PD automático.",
        }
    )
    embed = AusenciaRenderer().render_overdue_reminder(data)
    assert embed.title == "Sua ausência venceu"
    assert "PD autom" in str(embed.description)
