from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
try:
    from enum import StrEnum
except ImportError:  # Python 3.10 do servidor de teste
    from enum import Enum

    class StrEnum(str, Enum):
        pass
from hashlib import sha256
from typing import Iterable


class TagValidationError(ValueError):
    pass


class TagSyncState(StrEnum):
    pending = "pending"
    processing = "processing"
    retry = "retry"
    applied = "applied"
    skipped = "skipped"
    blocked = "blocked"
    failed = "failed"
    cancelled = "cancelled"


class TagSyncRunStatus(StrEnum):
    pending = "pending"
    planning = "planning"
    running = "running"
    completed = "completed"
    completed_with_errors = "completed_with_errors"
    cancelled = "cancelled"
    failed = "failed"


class TagSyncRunMode(StrEnum):
    effective = "effective"
    base_only = "base_only"


class TagResolutionStatus(StrEnum):
    change_required = "change_required"
    already_correct = "already_correct"
    blocked = "blocked"


MENTION_PATTERN = re.compile(r"<[@#][!&]?\d+>|<t:\d+(?::[tTdDfFR])?>", re.IGNORECASE)


def normalize_snowflake(value: str, *, field: str = "Discord ID") -> str:
    normalized = str(value).strip()
    if not normalized.isdecimal() or int(normalized) <= 0 or len(normalized) > 32:
        raise TagValidationError(f"{field} deve ser um snowflake decimal valido.")
    return normalized


def normalize_tag(value: str) -> str:
    raw = unicodedata.normalize("NFKC", str(value))
    if any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in raw):
        raise TagValidationError("A Tag contem caractere de controle ou invisivel.")
    normalized = " ".join(raw.split())
    lowered = normalized.casefold()
    if (
        "@everyone" in lowered
        or "@here" in lowered
        or any(token in normalized for token in ("<@", "<#", "<t:"))
        or MENTION_PATTERN.search(normalized)
    ):
        raise TagValidationError("A Tag nao pode conter mencoes do Discord.")
    visible = sum(
        1
        for char in normalized
        if not char.isspace() and unicodedata.category(char) not in {"Mn", "Me"}
    )
    if visible < 1 or visible > 12:
        raise TagValidationError("A Tag deve possuir de 1 a 12 caracteres visiveis.")
    return normalized


def discord_state_fingerprint(
    *, role_ids: Iterable[str], hierarchy_role_ids: Iterable[str], nickname: str | None
) -> str:
    payload = "|".join(
        (
            ",".join(str(item) for item in role_ids),
            ",".join(str(item) for item in hierarchy_role_ids),
            nickname or "",
        )
    )
    return sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TagBinding:
    discord_role_id: str
    tag: str
    enabled: bool = True


@dataclass(frozen=True)
class MemberDiscordSnapshot:
    guild_id: str
    discord_user_id: str
    member_found: bool
    role_ids: tuple[str, ...]
    hierarchy_role_ids: tuple[str, ...]
    current_nickname: str | None
    is_bot: bool = False
    is_owner: bool = False
    manage_nicknames: bool = False
    bot_top_role_id: str | None = None
    target_top_role_id: str | None = None


@dataclass(frozen=True)
class TagResolution:
    status: TagResolutionStatus
    expected_nickname: str | None
    winning_role_id: str | None = None
    winning_tag: str | None = None
    blocker: str | None = None
    reason: str | None = None


def resolve_tag(
    *,
    base_nickname: str,
    snapshot: MemberDiscordSnapshot,
    bindings: Iterable[TagBinding],
    base_only: bool = False,
) -> TagResolution:
    hierarchy = snapshot.hierarchy_role_ids
    if len(hierarchy) != len(set(hierarchy)):
        raise TagValidationError("A hierarquia do Discord possui IDs duplicados.")
    if not snapshot.member_found:
        return TagResolution(TagResolutionStatus.blocked, None, blocker="member_not_found")
    if snapshot.is_bot:
        return TagResolution(TagResolutionStatus.blocked, None, blocker="target_is_bot")

    rank = {role_id: index for index, role_id in enumerate(hierarchy)}
    member_roles = set(snapshot.role_ids)
    candidates = [
        item
        for item in bindings
        if item.enabled and item.discord_role_id in member_roles and item.discord_role_id in rank
    ]
    winner = max(candidates, key=lambda item: rank[item.discord_role_id]) if candidates and not base_only else None
    expected = base_nickname if winner is None else f"{winner.tag} {base_nickname}"
    if len(expected) > 32:
        return TagResolution(
            TagResolutionStatus.blocked,
            expected,
            winning_role_id=winner.discord_role_id if winner else None,
            winning_tag=winner.tag if winner else None,
            blocker="nickname_too_long",
        )
    if snapshot.current_nickname == expected:
        return TagResolution(
            TagResolutionStatus.already_correct,
            expected,
            winning_role_id=winner.discord_role_id if winner else None,
            winning_tag=winner.tag if winner else None,
            reason="already_correct",
        )
    if snapshot.is_owner:
        blocker = "member_is_owner"
    elif not snapshot.manage_nicknames:
        blocker = "manage_nicknames_missing"
    elif snapshot.bot_top_role_id is None or snapshot.target_top_role_id is None:
        blocker = "hierarchy_blocked"
    elif rank.get(snapshot.target_top_role_id, -1) >= rank.get(snapshot.bot_top_role_id, -1):
        blocker = "hierarchy_blocked"
    else:
        blocker = None
    if blocker:
        return TagResolution(
            TagResolutionStatus.blocked,
            expected,
            winning_role_id=winner.discord_role_id if winner else None,
            winning_tag=winner.tag if winner else None,
            blocker=blocker,
        )
    return TagResolution(
        TagResolutionStatus.change_required,
        expected,
        winning_role_id=winner.discord_role_id if winner else None,
        winning_tag=winner.tag if winner else None,
    )
