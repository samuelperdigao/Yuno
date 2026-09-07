from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain_modules.parceria.domain import ALLOWED_IMAGE_TYPES, MAX_IMAGE_BYTES
from app.platform.schemas import ActorContextIn


class ParceriaConfiguration(BaseModel):
    registrar_channel_id: str = Field(min_length=1, max_length=32)
    ativas_channel_id: str = Field(min_length=1, max_length=32)
    manager_role_ids: list[str] = Field(min_length=1, max_length=25)
    category_id: str | None = Field(default=None, max_length=32)
    log_channel_id: str | None = Field(default=None, max_length=32)


class RegistrationAttemptCreate(BaseModel):
    family_name: str = Field(min_length=1, max_length=100)
    product_name: str = Field(min_length=1, max_length=100)
    contacts: list[str] = Field(default_factory=list, max_length=2)
    channel_id: str = Field(min_length=1, max_length=32)
    idempotency_key: str = Field(min_length=1, max_length=160)

    @field_validator("family_name", "product_name")
    @classmethod
    def compact_text(cls, value: str) -> str:
        value = " ".join(value.strip().split())
        if not value:
            raise ValueError("O texto não pode ficar vazio.")
        return value


class RegistrationAttemptCommand(RegistrationAttemptCreate):
    actor: ActorContextIn


class ImageAttachIn(BaseModel):
    storage_key: str | None = Field(default=None, min_length=1, max_length=255)
    storage_url: str | None = Field(default=None, max_length=1000)
    content_type: str | None = None
    size_bytes: int | None = Field(default=None, gt=0, le=MAX_IMAGE_BYTES)
    checksum: str | None = Field(default=None, max_length=128)
    original_filename: str | None = Field(default=None, max_length=255)
    source_url: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_source(self) -> "ImageAttachIn":
        if self.source_url:
            return self
        if not self.storage_key or not self.content_type or self.size_bytes is None:
            raise ValueError("Informe source_url ou os metadados completos do asset.")
        return self


class ImageAttachCommand(ImageAttachIn):
    actor: ActorContextIn


class RegistrationCompleteCommand(BaseModel):
    actor: ActorContextIn


class PartnershipEditIn(BaseModel):
    family_name: str = Field(min_length=1, max_length=100)
    product_name: str = Field(min_length=1, max_length=100)
    contacts: list[str] = Field(default_factory=list, max_length=2)
    expected_revision: int = Field(ge=1)


class PartnershipEditCommand(PartnershipEditIn):
    actor: ActorContextIn


class PartnershipDeactivateCommand(BaseModel):
    expected_revision: int = Field(ge=1)
    actor: ActorContextIn


class AutomationCommand(BaseModel):
    actor: ActorContextIn
    attempt_id: str | None = Field(default=None, min_length=1, max_length=36)


class PublicationResultCommand(BaseModel):
    actor: ActorContextIn
    revision: int = Field(ge=1)
    status: str = Field(pattern=r"^(published|missing|failed)$")
    channel_id: str = Field(min_length=1, max_length=32)
    message_id: str | None = Field(default=None, max_length=32)
    error: str | None = Field(default=None, max_length=2000)


class PartnershipOut(BaseModel):
    id: str
    guild_id: str
    family_name: str
    family_normalized: str
    product_name: str
    contacts: list[str]
    status: str
    registered_by: str
    image: dict[str, Any]
    public_channel_id: str | None
    public_message_id: str | None
    publication_revision: int
    created_at: datetime
    updated_at: datetime


class RegistrationAttemptOut(BaseModel):
    id: str
    guild_id: str
    actor_id: str
    channel_id: str
    family_name: str
    product_name: str
    contacts: list[str]
    status: str
    expires_at: datetime
    image_asset_id: str | None
    completed_parceria_id: str | None


def image_contract() -> dict[str, Any]:
    return {"content_types": sorted(ALLOWED_IMAGE_TYPES), "max_bytes": MAX_IMAGE_BYTES}
