import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.domain_modules.tags.domain import (  # noqa: E402
    MemberDiscordSnapshot,
    TagBinding,
    TagResolutionStatus,
    TagValidationError,
    normalize_tag,
    resolve_tag,
)


def snapshot(
    *,
    roles=("1", "10", "20"),
    hierarchy=("1", "10", "20", "90"),
    nickname="Mineiro | 6627",
    **overrides,
):
    data = {
        "guild_id": "1",
        "discord_user_id": "2",
        "member_found": True,
        "role_ids": roles,
        "hierarchy_role_ids": hierarchy,
        "current_nickname": nickname,
        "manage_nicknames": True,
        "bot_top_role_id": "90",
        "target_top_role_id": "20",
    }
    data.update(overrides)
    return MemberDiscordSnapshot(**data)


def test_tag_normalization_and_rejections() -> None:
    assert normalize_tag("  ［MEM］   Geral  ") == "[MEM] Geral"
    assert normalize_tag("[MEM]") == "[MEM]"
    for value in (
        "",
        "   ",
        "@everyone",
        "<@123>",
        "<@abc",
        "linha\nnova",
        "tab\tnao",
        "ok\u200b",
        "ABCDEFGHIJKLM",
    ):
        with pytest.raises(TagValidationError):
            normalize_tag(value)


def test_resolution_uses_live_hierarchy_and_only_one_tag() -> None:
    bindings = [TagBinding("10", "[MEM]"), TagBinding("20", "[GER]")]
    result = resolve_tag(base_nickname="Mineiro | 6627", snapshot=snapshot(), bindings=bindings)
    assert result.status == TagResolutionStatus.change_required
    assert result.expected_nickname == "[GER] Mineiro | 6627"
    assert result.winning_role_id == "20"

    reordered = snapshot(hierarchy=("1", "20", "10", "90"), target_top_role_id="10")
    result = resolve_tag(base_nickname="Mineiro | 6627", snapshot=reordered, bindings=bindings)
    assert result.expected_nickname == "[MEM] Mineiro | 6627"


def test_resolution_ignores_orphan_disabled_and_falls_back_to_base() -> None:
    bindings = [TagBinding("999", "[OLD]"), TagBinding("10", "[MEM]", enabled=False)]
    result = resolve_tag(base_nickname="Mineiro | 6627", snapshot=snapshot(), bindings=bindings)
    assert result.expected_nickname == "Mineiro | 6627"
    assert result.status == TagResolutionStatus.already_correct


@pytest.mark.parametrize(
    ("changes", "blocker"),
    [
        ({"is_bot": True}, "target_is_bot"),
        ({"is_owner": True}, "member_is_owner"),
        ({"manage_nicknames": False}, "manage_nicknames_missing"),
        ({"bot_top_role_id": "10", "target_top_role_id": "20"}, "hierarchy_blocked"),
        ({"member_found": False}, "member_not_found"),
    ],
)
def test_resolution_returns_structured_blockers(changes, blocker) -> None:
    result = resolve_tag(
        base_nickname="Mineiro | 6627",
        snapshot=snapshot(**changes),
        bindings=[TagBinding("10", "[MEM]")],
    )
    assert result.status == TagResolutionStatus.blocked
    assert result.blocker == blocker


def test_resolution_blocks_over_32_without_truncation_and_validates_hierarchy() -> None:
    result = resolve_tag(
        base_nickname="A" * 28,
        snapshot=snapshot(nickname=None),
        bindings=[TagBinding("10", "[MEM]")],
    )
    assert result.blocker == "nickname_too_long"
    assert result.expected_nickname == "[MEM] " + "A" * 28

    with pytest.raises(TagValidationError):
        resolve_tag(
            base_nickname="Mineiro | 6627",
            snapshot=snapshot(hierarchy=("1", "10", "10", "90")),
            bindings=[],
        )


def test_base_only_cleanup_ignores_winning_binding() -> None:
    result = resolve_tag(
        base_nickname="Mineiro | 6627",
        snapshot=snapshot(nickname="[MEM] Mineiro | 6627"),
        bindings=[TagBinding("10", "[MEM]")],
        base_only=True,
    )
    assert result.expected_nickname == "Mineiro | 6627"
    assert result.status == TagResolutionStatus.change_required
