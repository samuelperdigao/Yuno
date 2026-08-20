from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domain_modules.tags.domain import TagSyncRunMode
from app.platform.schemas import ActorContextIn


class TagBindingUpsertIn(BaseModel):
    discord_role_id: str = Field(min_length=1, max_length=32)
    guild_role_ids: list[str] = Field(min_length=1, max_length=500)
    tag: str = Field(min_length=1, max_length=64)
    enabled: bool = True
    expected_revision: int = Field(ge=0)
    expected_published_version: int = Field(ge=0)
    actor: ActorContextIn


class TagBindingDeleteIn(BaseModel):
    expected_revision: int = Field(ge=0)
    expected_published_version: int = Field(ge=0)
    actor: ActorContextIn


class MemberDiscordSnapshotIn(BaseModel):
    guild_id: str = Field(min_length=1, max_length=32)
    discord_user_id: str = Field(min_length=1, max_length=32)
    member_found: bool = True
    role_ids: list[str] = Field(default_factory=list, max_length=500)
    hierarchy_role_ids: list[str] = Field(default_factory=list, max_length=500)
    current_nickname: str | None = Field(default=None, max_length=32)
    is_bot: bool = False
    is_owner: bool = False
    manage_nicknames: bool = False
    bot_top_role_id: str | None = Field(default=None, max_length=32)
    target_top_role_id: str | None = Field(default=None, max_length=32)


class TagPreviewIn(BaseModel):
    snapshot: MemberDiscordSnapshotIn
    source: Literal["draft", "effective"] = "effective"
    base_only: bool = False
    actor: ActorContextIn


class TagMemberDiagnosticsIn(BaseModel):
    snapshot: MemberDiscordSnapshotIn
    actor: ActorContextIn


class TagMemberSyncRequestIn(BaseModel):
    discord_user_id: str = Field(min_length=1, max_length=32)
    observed_fingerprint: str | None = Field(default=None, max_length=64)
    reason: str = Field(default="event", min_length=1, max_length=80)
    actor: ActorContextIn


class TagSyncPrepareIn(BaseModel):
    intent_id: str = Field(min_length=1, max_length=36)
    revision: int = Field(ge=1)
    run_item_id: str | None = Field(default=None, max_length=36)
    snapshot: MemberDiscordSnapshotIn
    actor: ActorContextIn


class TagSyncCompleteIn(BaseModel):
    intent_id: str = Field(min_length=1, max_length=36)
    revision: int = Field(ge=1)
    processing_token: str = Field(min_length=1, max_length=64)
    run_item_id: str | None = Field(default=None, max_length=36)
    result: Literal["applied", "already_correct", "blocked", "skipped"]
    result_code: str = Field(min_length=1, max_length=120)
    applied_nickname_hash: str | None = Field(default=None, max_length=64)
    actor: ActorContextIn


class TagSyncFailIn(BaseModel):
    intent_id: str = Field(min_length=1, max_length=36)
    revision: int = Field(ge=1)
    processing_token: str = Field(min_length=1, max_length=64)
    run_item_id: str | None = Field(default=None, max_length=36)
    error_code: str = Field(min_length=1, max_length=120)
    error_detail: str = Field(default="", max_length=500)
    retryable: bool = False
    actor: ActorContextIn


class TagSyncRunCreateIn(BaseModel):
    mode: TagSyncRunMode = TagSyncRunMode.effective
    reason: str = Field(default="manual", min_length=1, max_length=80)
    supersede_active: bool = False
    actor: ActorContextIn


class TagSyncRunCancelIn(BaseModel):
    actor: ActorContextIn


class TagRunJobIn(BaseModel):
    job_key: Literal["tags.run.plan", "tags.run.finalize", "tags.retention"]
    payload: dict[str, Any] = Field(default_factory=dict)
    actor: ActorContextIn


class TagPeriodicEnsureIn(BaseModel):
    day_key: str = Field(min_length=10, max_length=10)
    actor: ActorContextIn


class TagMemberCancelIn(BaseModel):
    discord_user_id: str = Field(min_length=1, max_length=32)
    actor: ActorContextIn
