from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.domain_modules.meta.domain import (  # noqa: E402
    EligibleMember,
    MetaDomainError,
    ParticipationKind,
    RecurrenceKind,
    eligible_members,
    next_boundary,
    normalize_decimal,
    resolve_local,
)
from app.domain_modules.meta.schemas import MetaGoalConfigurationIn  # noqa: E402


def test_item_decimal_accepts_three_places_and_rejects_four() -> None:
    assert normalize_decimal("10.125", places=3) == Decimal("10.125")
    with pytest.raises(MetaDomainError):
        normalize_decimal("10.1251", places=3)


def test_money_decimal_accepts_two_places_and_never_float() -> None:
    assert normalize_decimal("1500.25", places=2) == Decimal("1500.25")
    with pytest.raises(MetaDomainError):
        normalize_decimal("1500.251", places=2)


def test_daily_boundary_uses_configured_local_clock() -> None:
    result = next_boundary(
        recurrence=RecurrenceKind.daily,
        after=datetime(2026, 8, 22, 2, 0, tzinfo=timezone.utc),
        timezone_name="America/Sao_Paulo",
        daily_time="23:55",
    )
    assert result == datetime(2026, 8, 22, 2, 55, tzinfo=timezone.utc)


def test_weekly_boundary_is_local_midnight() -> None:
    result = next_boundary(
        recurrence=RecurrenceKind.weekly,
        after=datetime(2026, 8, 22, 15, 0, tzinfo=timezone.utc),
        timezone_name="America/Sao_Paulo",
        weekday=0,
    )
    assert result == datetime(2026, 8, 24, 3, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("after", "expected"),
    [
        (datetime(2027, 2, 1, tzinfo=timezone.utc), datetime(2027, 2, 28, 3, tzinfo=timezone.utc)),
        (datetime(2028, 2, 1, tzinfo=timezone.utc), datetime(2028, 2, 29, 3, tzinfo=timezone.utc)),
    ],
)
def test_month_day_31_clamps_to_february(after: datetime, expected: datetime) -> None:
    assert next_boundary(
        recurrence=RecurrenceKind.monthly,
        after=after,
        timezone_name="America/Sao_Paulo",
        month_day=31,
    ) == expected


def test_nonexistent_dst_time_advances_to_first_valid_minute() -> None:
    resolved = resolve_local(datetime(2026, 3, 8, 2, 30), "America/New_York")
    assert resolved.hour == 3 and resolved.minute == 0


def test_ambiguous_dst_time_uses_first_occurrence() -> None:
    resolved = resolve_local(datetime(2026, 11, 1, 1, 30), "America/New_York")
    assert resolved.fold == 0
    assert resolved.utcoffset().total_seconds() == -4 * 3600


def test_eligibility_supports_all_or_role_union_without_domain_limit() -> None:
    members = tuple(
        EligibleMember(str(index), f"Membro {index}", (str(100 + index % 30),))
        for index in range(60)
    )
    assert len(
        eligible_members(
            members,
            participation=ParticipationKind.all_members,
            role_ids=(),
        )
    ) == 60
    selected = eligible_members(
        members,
        participation=ParticipationKind.roles,
        role_ids=tuple(str(100 + value) for value in range(25)),
    )
    assert len(selected) == 50
    validated = MetaGoalConfigurationIn.model_validate(
        {
            "name": "Sem limite visual",
            "recurrence": "weekly",
            "timezone": "America/Sao_Paulo",
            "weekday": 0,
            "participation": "roles",
            "role_ids": [str(value) for value in range(30)],
            "objectives": [
                {"kind": "money", "name": "Dinheiro", "money_amount": "100.00"}
            ],
            "notice_text": "Aviso",
        }
    )
    assert len(validated.role_ids) == 30


def test_custom_goal_requires_both_aware_dates() -> None:
    with pytest.raises(ValueError):
        MetaGoalConfigurationIn.model_validate(
            {
                "name": "Personalizada",
                "recurrence": "custom",
                "timezone": "America/Sao_Paulo",
                "scheduled_start_at": "2026-08-22T20:00:00-03:00",
                "participation": "all_members",
                "role_ids": [],
                "objectives": [
                    {"kind": "money", "name": "Dinheiro", "money_amount": "100.00"}
                ],
                "notice_text": "Aviso",
            }
        )
    normalized = MetaGoalConfigurationIn.model_validate(
        {
            "name": "Personalizada DST",
            "recurrence": "custom",
            "timezone": "America/New_York",
            "scheduled_start_at": "2026-03-08T02:30:00-05:00",
            "scheduled_end_at": "2026-03-08T04:00:00-04:00",
            "participation": "all_members",
            "role_ids": [],
            "objectives": [
                {"kind": "money", "name": "Dinheiro", "money_amount": "100.00"}
            ],
            "notice_text": "Aviso",
        }
    )
    assert normalized.scheduled_start_at.hour == 3
    assert normalized.scheduled_start_at.fold == 0
