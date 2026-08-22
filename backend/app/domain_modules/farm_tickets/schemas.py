from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.domain_modules.farm_tickets.domain import FormKind, OperationKind
from app.platform.schemas import ActorContextIn


class MutatingTicketActionIn(BaseModel):
    actor: ActorContextIn
    expected_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=180)


class OpenTicketIn(BaseModel):
    member_id: str = Field(min_length=1, max_length=32)
    actor: ActorContextIn
    idempotency_key: str = Field(min_length=1, max_length=180)


class ObjectiveAmountIn(BaseModel):
    objective_id: str = Field(min_length=1, max_length=36)
    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=3)


class DraftObjectiveAmountIn(BaseModel):
    objective_id: str = Field(min_length=1, max_length=36)
    amount: Decimal = Field(ge=0, max_digits=20, decimal_places=3)


class BeginOperationIn(MutatingTicketActionIn):
    kind: OperationKind
    target_entry_id: str | None = Field(default=None, max_length=36)
    interaction_id: str | None = Field(default=None, max_length=32)
    values: list[ObjectiveAmountIn] = Field(min_length=1)

    @field_validator("target_entry_id")
    @classmethod
    def validate_target(cls, value: str | None, info):
        kind = info.data.get("kind")
        if kind == OperationKind.EDIT_ENTRY and not value:
            raise ValueError("target_entry_id e obrigatorio para edicao.")
        if kind == OperationKind.CREATE_ENTRY and value:
            raise ValueError("target_entry_id nao e aceito em novo lancamento.")
        return value


class OpenFormIn(MutatingTicketActionIn):
    kind: FormKind
    target_entry_id: str | None = Field(default=None, max_length=36)


class SaveFormStepIn(MutatingTicketActionIn):
    draft_revision: int = Field(ge=1)
    step: int = Field(ge=0)
    interaction_id: str | None = Field(default=None, max_length=32)
    values: list[DraftObjectiveAmountIn] = Field(min_length=1, max_length=5)


class ProofClaimIn(MutatingTicketActionIn):
    message_id: str = Field(min_length=1, max_length=32)
    attachment_id: str = Field(min_length=1, max_length=32)
    author_id: str = Field(min_length=1, max_length=32)
    channel_id: str = Field(min_length=1, max_length=32)
    received_at: datetime
    filename: str = Field(min_length=1, max_length=255)
    content_type: str | None = Field(default=None, max_length=100)
    size_bytes: int = Field(gt=0, le=20 * 1024 * 1024)
    source_url: str = Field(min_length=1, max_length=2048)


class ProofProcessIn(MutatingTicketActionIn):
    claim_token: str = Field(min_length=32, max_length=72)


class ProofConfirmIn(ProofProcessIn):
    object_key: str = Field(min_length=1, max_length=500)
    checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0, le=20 * 1024 * 1024)
    content_type: str = Field(min_length=1, max_length=100)


class ProofRejectIn(ProofProcessIn):
    reason: str = Field(min_length=1, max_length=500)


class ProofRetryIn(ProofProcessIn):
    error: str = Field(min_length=1, max_length=2000)


class WithdrawalIn(MutatingTicketActionIn):
    values: list[ObjectiveAmountIn] = Field(min_length=1)


class AssignTicketIn(MutatingTicketActionIn):
    administrator_id: str = Field(min_length=1, max_length=32)


class CloseTicketIn(MutatingTicketActionIn):
    reason: str | None = Field(default=None, max_length=500)


class MetaConsumeIn(BaseModel):
    actor: ActorContextIn
    limit: int = Field(default=100, ge=1, le=500)


class ReconcileIn(BaseModel):
    actor: ActorContextIn
    idempotency_key: str = Field(min_length=1, max_length=180)


class DiscordBindingIn(BaseModel):
    actor: ActorContextIn
    idempotency_key: str = Field(min_length=1, max_length=180)
    ticket_id: str | None = Field(default=None, max_length=36)
    kind: str = Field(min_length=1, max_length=32)
    resource_id: str = Field(min_length=1, max_length=32)
    parent_resource_id: str | None = Field(default=None, max_length=32)
    ownership: str = Field(pattern="^(ADOPTED|MANAGED)$")


class ProvisioningErrorIn(BaseModel):
    actor: ActorContextIn
    ticket_id: str = Field(min_length=1, max_length=36)
    error: str | None = Field(default=None, max_length=2000)


class ProofDeliveredIn(BaseModel):
    actor: ActorContextIn
    external_message_id: str = Field(min_length=1, max_length=32)


class AutomationIn(BaseModel):
    actor: ActorContextIn
    idempotency_key: str = Field(min_length=1, max_length=180)


class ResourceDeletedIn(BaseModel):
    actor: ActorContextIn
    resource_id: str = Field(min_length=1, max_length=32)
    observed_at: datetime


class TicketOut(BaseModel):
    id: str
    guild_id: str
    member_id: str
    member_name: str
    player_id: str
    meta_goal_id: int
    meta_cycle_id: int
    status: str
    revision: int
    operations_open: bool
    withdrawals_open: bool
    launched: dict[str, str]
    withdrawn: dict[str, str]
    available: dict[str, str]
    progress_percent: str
    active_operation: dict | None = None
