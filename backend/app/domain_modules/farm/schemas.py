from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain_modules.farm.domain import ParticipationMode, ReviewDecision, normalize_name
from app.platform.schemas import ActorContextIn


class FarmSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProductCreate(FarmSchema):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    unit: str = Field(min_length=1, max_length=30)
    precision: int = Field(default=0, ge=0, le=3)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if not normalize_name(value):
            raise ValueError("Nome obrigatorio.")
        return " ".join(value.split())


class TemplateItemInput(FarmSchema):
    product_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=3)


class TemplateCreate(FarmSchema):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    items: list[TemplateItemInput] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_products(self) -> "TemplateCreate":
        product_ids = [item.product_id for item in self.items]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("Produto duplicado no template.")
        return self


class CycleCreate(FarmSchema):
    template_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=120)
    timezone: str = Field(min_length=1, max_length=64)
    starts_at: datetime
    ends_at: datetime
    review_deadline_at: datetime | None = None
    participation_mode: ParticipationMode = ParticipationMode.opt_in
    proof_required: bool = True

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Timezone IANA invalido.") from exc
        return value

    @model_validator(mode="after")
    def valid_dates(self) -> "CycleCreate":
        if self.starts_at.utcoffset() is None or self.ends_at.utcoffset() is None:
            raise ValueError("Inicio e fim devem incluir timezone.")
        if self.review_deadline_at is not None and self.review_deadline_at.utcoffset() is None:
            raise ValueError("Prazo de revisao deve incluir timezone.")
        if self.ends_at <= self.starts_at:
            raise ValueError("Fim do ciclo deve ser posterior ao inicio.")
        if self.review_deadline_at is not None and self.review_deadline_at < self.ends_at:
            raise ValueError("Prazo de revisao nao pode anteceder o fim do ciclo.")
        return self


class TicketOpen(FarmSchema):
    member_id: str = Field(min_length=1, max_length=32)
    member_display_name: str = Field(min_length=1, max_length=120)
    created_by: str = Field(min_length=1, max_length=32)


class SubmissionItemInput(FarmSchema):
    goal_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=3)


class ProofInput(FarmSchema):
    channel_id: str = Field(min_length=1, max_length=32)
    message_id: str = Field(min_length=1, max_length=32)
    attachment_id: str | None = Field(default=None, max_length=32)
    url: str = Field(min_length=1, max_length=2000)
    content_type: str | None = Field(default=None, max_length=120)

    @field_validator("url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        if not value.startswith(("https://", "http://")):
            raise ValueError("Comprovante deve ser uma URL HTTP(S).")
        return value


class SubmissionCreate(FarmSchema):
    submitted_by: str = Field(min_length=1, max_length=32)
    items: list[SubmissionItemInput] = Field(min_length=1)
    proofs: list[ProofInput] = Field(min_length=1)
    correction_of_submission_id: int | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=1000)
    idempotency_key: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def unique_goals(self) -> "SubmissionCreate":
        goal_ids = [item.goal_id for item in self.items]
        if len(goal_ids) != len(set(goal_ids)):
            raise ValueError("Meta duplicada na entrega.")
        return self


class ReviewCreate(FarmSchema):
    reviewer_id: str = Field(min_length=1, max_length=32)
    decision: ReviewDecision
    reason: str | None = Field(default=None, max_length=1000)
    idempotency_key: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def reason_for_negative_decision(self) -> "ReviewCreate":
        if self.decision != ReviewDecision.approved and not (self.reason or "").strip():
            raise ValueError("Justificativa obrigatoria para rejeicao ou correcao.")
        return self


class ProductCreateCommand(FarmSchema):
    actor: ActorContextIn
    product: ProductCreate


class ProductArchiveCommand(FarmSchema):
    actor: ActorContextIn
    expected_revision: int = Field(gt=0)


class TemplateCreateCommand(FarmSchema):
    actor: ActorContextIn
    template: TemplateCreate


class RevisionCommand(FarmSchema):
    actor: ActorContextIn
    expected_revision: int = Field(gt=0)
    reason: str | None = Field(default=None, max_length=1000)


class CycleCreateCommand(FarmSchema):
    actor: ActorContextIn
    cycle: CycleCreate


class TicketOpenCommand(FarmSchema):
    actor: ActorContextIn
    member_id: str = Field(min_length=1, max_length=32)
    member_display_name: str = Field(min_length=1, max_length=120)


class ParticipantAssignCommand(FarmSchema):
    actor: ActorContextIn
    member_id: str = Field(min_length=1, max_length=32)
    member_display_name: str = Field(min_length=1, max_length=120)


class CycleTransitionCommand(FarmSchema):
    actor: ActorContextIn
    expected_revision: int = Field(gt=0)
    reason: str | None = Field(default=None, max_length=1000)


class SubmissionCreateCommand(FarmSchema):
    actor: ActorContextIn
    submission: SubmissionCreate


class ReviewCreateCommand(FarmSchema):
    actor: ActorContextIn
    review: ReviewCreate
