from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models import LicenseStatus, RecordStatus


MODULES = [
    "set",
    "meta",
    "ticket",
    "parceria",
    "encomenda",
    "ausencia",
    "radio",
    "producao",
]


def default_modules() -> dict[str, bool]:
    return {module: True for module in MODULES}


class LicenseActivateIn(BaseModel):
    license_key: str = Field(min_length=8)
    guild_id: str
    guild_name: str | None = None
    owner_discord_id: str


class LicenseOut(BaseModel):
    key: str
    status: LicenseStatus
    guild_id: str | None = None
    guild_name: str | None = None
    activated_at: datetime | None = None


class LicenseValidateIn(BaseModel):
    guild_id: str


class LicenseValidateOut(BaseModel):
    allowed: bool
    status: LicenseStatus | Literal["missing"]
    guild_id: str
    modules: dict[str, bool] = Field(default_factory=default_modules)


class PermissionCheckIn(BaseModel):
    guild_id: str
    module: str
    command: str
    user_role_ids: list[str] = Field(default_factory=list)
    channel_id: str | None = None
    category_id: str | None = None


class PermissionCheckOut(BaseModel):
    allowed: bool
    reason: str


class GuildConfigIn(BaseModel):
    guild_name: str | None = None
    admin_role_ids: list[str] = Field(default_factory=list)
    log_channel_id: str | None = None
    modules: dict[str, bool] = Field(default_factory=default_modules)
    command_permissions: dict[str, Any] = Field(default_factory=dict)
    messages: dict[str, Any] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)


class GuildConfigOut(GuildConfigIn):
    guild_id: str


class ProductIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    unit: str = Field(default="unidade", max_length=40)
    active: bool = True


class ProductOut(ProductIn):
    id: int
    guild_id: str


class SystemRecordIn(BaseModel):
    guild_id: str
    title: str = Field(min_length=2, max_length=160)
    requester_id: str
    channel_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class SystemRecordPatch(BaseModel):
    status: RecordStatus
    reviewer_id: str | None = None
    payload: dict[str, Any] | None = None


class SystemRecordOut(BaseModel):
    id: int
    guild_id: str
    module: str
    status: RecordStatus
    title: str
    requester_id: str
    reviewer_id: str | None = None
    channel_id: str | None = None
    payload: dict[str, Any]
    created_at: datetime
    reviewed_at: datetime | None = None


class DashboardSessionOut(BaseModel):
    token: str
    user: dict[str, Any]
    guilds: list[dict[str, Any]]


class MercadoPagoWebhookOut(BaseModel):
    accepted: bool
    license_key: str | None = None
    duplicate: bool = False
