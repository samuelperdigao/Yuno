from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.domain_modules.chest.domain import MovementType, compact_text, quantity
from app.platform.schemas import ActorContextIn, PermissionGrantIn


class ChestConfiguration(BaseModel):
    panel_channel_id: str = Field(min_length=1, max_length=32)
    log_channel_id: str | None = Field(default=None, max_length=32)
    show_balances_to_members: bool = True
    allow_personal_history: bool = True
    withdrawal_reason_required: bool = True
    operator_role_ids: list[str] = Field(default_factory=list, max_length=25)
    panel_title: str = Field(default="Sistema de Bau", min_length=1, max_length=80)
    panel_description: str = Field(
        default="Consulte o estoque e registre depositos ou retiradas autorizadas.",
        min_length=1,
        max_length=300,
    )

    @field_validator("panel_title", "panel_description")
    @classmethod
    def compact(cls, value: str) -> str:
        return compact_text(value, max_length=300)


class MutationContext(BaseModel):
    expected_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=160)
    actor: ActorContextIn


class ActorCommand(BaseModel):
    actor: ActorContextIn


class SettingsDraftCommand(MutationContext):
    expected_published_version: int = Field(ge=0)
    schema_version: int = Field(default=1, ge=1)
    data: ChestConfiguration


class ChestDraftUpsert(MutationContext):
    chest_id: str | None = Field(default=None, max_length=36)
    name: str = Field(min_length=1, max_length=100)
    active: bool = True
    position: int = Field(default=0, ge=0, le=100000)


class ItemDraftUpsert(MutationContext):
    item_id: str | None = Field(default=None, max_length=36)
    name: str = Field(min_length=1, max_length=100)
    unit: str = Field(default="unidade", min_length=1, max_length=40)
    active: bool = True
    position: int = Field(default=0, ge=0, le=100000)


class LinkDraftUpsert(MutationContext):
    chest_id: str = Field(min_length=36, max_length=36)
    item_id: str = Field(min_length=36, max_length=36)
    active: bool = True


class CatalogPublishCommand(BaseModel):
    expected_revision: int = Field(ge=0)
    expected_published_version: int = Field(ge=0)
    grants: list[PermissionGrantIn] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=1, max_length=160)
    actor: ActorContextIn


class MovementCommand(BaseModel):
    chest_id: str = Field(min_length=36, max_length=36)
    item_id: str = Field(min_length=36, max_length=36)
    movement_type: MovementType
    quantity: Decimal
    observation: str | None = Field(default=None, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=160)
    origin: str = Field(default="discord", min_length=1, max_length=64)
    actor: ActorContextIn

    @field_validator("quantity")
    @classmethod
    def valid_quantity(cls, value: Decimal) -> Decimal:
        return quantity(value)

    @field_validator("observation")
    @classmethod
    def compact_observation(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return compact_text(value, field="observacao", max_length=500)


class ExternalDepositCommand(BaseModel):
    source_module: str = Field(min_length=1, max_length=64)
    source_event_id: str = Field(min_length=1, max_length=120)
    chest_id: str = Field(min_length=36, max_length=36)
    item_id: str = Field(min_length=36, max_length=36)
    quantity: Decimal
    observation: str | None = Field(default=None, max_length=500)
    actor: ActorContextIn

    @field_validator("quantity")
    @classmethod
    def valid_quantity(cls, value: Decimal) -> Decimal:
        return quantity(value)


class HistoryQuery(BaseModel):
    chest_id: str | None = Field(default=None, max_length=36)
    item_id: str | None = Field(default=None, max_length=36)
    actor_id: str | None = Field(default=None, max_length=32)
    limit: int = Field(default=25, ge=1, le=100)
    before_sequence: int | None = Field(default=None, ge=1)


class HistoryCommand(HistoryQuery):
    actor: ActorContextIn


class StockCommand(BaseModel):
    chest_id: str = Field(min_length=36, max_length=36)
    actor: ActorContextIn


class RecoveryCommand(BaseModel):
    action: Literal["create_missing_balances", "reconcile_panel"]
    idempotency_key: str = Field(min_length=1, max_length=160)
    actor: ActorContextIn


class ResourceDeletedCommand(BaseModel):
    resource_type: Literal["message", "channel", "thread"]
    resource_id: str = Field(min_length=1, max_length=32)
    idempotency_key: str = Field(min_length=1, max_length=160)
    actor: ActorContextIn
