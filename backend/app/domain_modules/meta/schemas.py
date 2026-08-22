from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain_modules.meta.domain import (
    ObjectiveKind,
    ParticipationKind,
    RecurrenceKind,
    normalize_timezone,
    parse_clock,
    resolve_local,
)
from app.platform.schemas import ActorContextIn


class MetaSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MetaSettingsIn(MetaSchema):
    notice_channel_id: str = Field(min_length=1, max_length=32)
    expected_revision: int | None = Field(default=None, ge=0)


class MetaSettingsCommand(MetaSettingsIn):
    actor: ActorContextIn


class MetaObjectiveIn(MetaSchema):
    kind: ObjectiveKind
    name: str = Field(min_length=1, max_length=100)
    unit: str | None = Field(default=None, min_length=1, max_length=30)
    item_quantity: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=3)
    money_amount: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=2)

    @model_validator(mode="after")
    def valid_shape(self) -> "MetaObjectiveIn":
        if self.kind == ObjectiveKind.item:
            if self.item_quantity is None or self.money_amount is not None or not self.unit:
                raise ValueError("Objetivo de item exige quantidade e unidade, sem valor em dinheiro.")
        elif self.money_amount is None or self.item_quantity is not None or self.unit is not None:
            raise ValueError("Objetivo de dinheiro exige apenas o valor monetario.")
        return self


class MetaGoalConfigurationIn(MetaSchema):
    name: str = Field(min_length=1, max_length=120)
    recurrence: RecurrenceKind
    timezone: str = Field(min_length=1, max_length=64)
    daily_time: str | None = None
    weekday: int | None = Field(default=None, ge=0, le=6)
    month_day: int | None = Field(default=None, ge=1, le=31)
    scheduled_start_at: datetime | None = None
    scheduled_end_at: datetime | None = None
    participation: ParticipationKind
    role_ids: list[str] = Field(default_factory=list)
    objectives: list[MetaObjectiveIn] = Field(min_length=1)
    notice_text: str = Field(min_length=1, max_length=2000)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        return normalize_timezone(value)

    @model_validator(mode="after")
    def valid_recurrence_and_participants(self) -> "MetaGoalConfigurationIn":
        if self.recurrence == RecurrenceKind.daily:
            parse_clock(self.daily_time or "")
        elif self.recurrence == RecurrenceKind.weekly and self.weekday is None:
            raise ValueError("Meta semanal exige o dia da semana.")
        elif self.recurrence == RecurrenceKind.monthly and self.month_day is None:
            raise ValueError("Meta mensal exige o dia do mes.")
        elif self.recurrence == RecurrenceKind.custom:
            if self.scheduled_start_at is None or self.scheduled_start_at.utcoffset() is None:
                raise ValueError("Meta personalizada exige inicio com timezone.")
            if self.scheduled_end_at is None or self.scheduled_end_at.utcoffset() is None:
                raise ValueError("Meta personalizada exige fim com timezone.")
            zone = ZoneInfo(self.timezone)
            start_local = self.scheduled_start_at.astimezone(zone).replace(tzinfo=None)
            end_local = self.scheduled_end_at.astimezone(zone).replace(tzinfo=None)
            self.scheduled_start_at = resolve_local(start_local, self.timezone)
            self.scheduled_end_at = resolve_local(end_local, self.timezone)
            if self.scheduled_end_at <= self.scheduled_start_at:
                raise ValueError("Fim da Meta personalizada deve ser posterior ao inicio.")
        if self.participation == ParticipationKind.roles and not self.role_ids:
            raise ValueError("Selecione ao menos um cargo participante.")
        if self.participation == ParticipationKind.all_members and self.role_ids:
            raise ValueError("Meta para todos nao aceita cargos especificos.")
        if len(self.role_ids) != len(set(self.role_ids)):
            raise ValueError("Cargo participante duplicado.")
        kinds = {item.kind for item in self.objectives}
        if not kinds.issubset({ObjectiveKind.item, ObjectiveKind.money}):
            raise ValueError("Tipo de objetivo invalido.")
        return self


class MetaDraftOpenIn(MetaSchema):
    goal_id: int | None = Field(default=None, gt=0)


class MetaDraftOpenCommand(MetaDraftOpenIn):
    actor: ActorContextIn


class MetaDraftPatchIn(MetaSchema):
    expected_revision: int = Field(gt=0)
    step: str = Field(min_length=1, max_length=32)
    patch: dict[str, Any]


class MetaDraftPatchCommand(MetaDraftPatchIn):
    actor: ActorContextIn


class MetaDraftSubmitIn(MetaSchema):
    expected_revision: int = Field(gt=0)


class MetaDraftSubmitCommand(MetaDraftSubmitIn):
    actor: ActorContextIn


class MetaMemberSnapshotIn(MetaSchema):
    member_id: str = Field(min_length=1, max_length=32)
    display_name: str = Field(min_length=1, max_length=120)
    role_ids: list[str] = Field(default_factory=list)


class MetaPrepareLaunchCommand(MetaSchema):
    members: list[MetaMemberSnapshotIn]
    notice_channel_id: str = Field(min_length=1, max_length=32)
    causation_id: str = Field(min_length=1, max_length=100)


class MetaActivateCycleCommand(MetaPrepareLaunchCommand):
    cycle_id: int = Field(gt=0)
    notice_message_id: str = Field(min_length=1, max_length=32)


class MetaCycleTransitionCommand(MetaSchema):
    cycle_id: int = Field(gt=0)
    causation_id: str = Field(min_length=1, max_length=100)


class MetaMemberRemoveCommand(MetaSchema):
    member_id: str = Field(min_length=1, max_length=32)
    causation_id: str = Field(min_length=1, max_length=100)


class MetaRecoveryCommand(MetaSchema):
    causation_id: str = Field(min_length=1, max_length=100)
