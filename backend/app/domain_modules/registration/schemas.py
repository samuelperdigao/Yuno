from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain_modules.registration.domain import (
    RegistrationDomainError,
    normalize_name,
    validate_nickname_template,
)
from app.platform.schemas import ActorContextIn


class RegistrationSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RegistrationConfig(RegistrationSchema):
    enabled: bool = True
    panel_channel_id: str = Field(default="", max_length=32)
    approval_channel_id: str = Field(default="", max_length=32)
    log_channel_id: str = Field(default="", max_length=32)
    member_role_id: str = Field(default="", max_length=32)
    approver_role_ids: list[str] = Field(default_factory=list)
    nickname_template: str = Field(default="{name} | {id}", min_length=1, max_length=80)
    player_id_numeric_only: bool = True
    player_id_min_length: int = Field(default=1, ge=1, le=32)
    player_id_max_length: int = Field(default=16, ge=1, le=32)
    name_min_length: int = Field(default=2, ge=1, le=32)
    name_max_length: int = Field(default=24, ge=1, le=32)
    allow_resubmit_after_rejection: bool = True
    panel_title: str = Field(default="Registro", min_length=1, max_length=256)
    panel_description: str = Field(
        default="Registre seu nome e ID para acessar a organizacao.",
        min_length=1,
        max_length=4000,
    )
    panel_instructions: str = Field(
        default="Clique no botao abaixo e preencha seus dados.",
        max_length=2000,
    )
    panel_footer: str = Field(default="Yuno", max_length=2048)
    panel_color: str = "#FFC72C"
    panel_banner_url: str = Field(default="", max_length=2000)
    panel_thumbnail_url: str = Field(default="", max_length=2000)
    button_label: str = Field(default="Fazer meu registro", min_length=1, max_length=80)
    button_emoji: str = Field(default="📝", max_length=32)
    submitted_message: str = Field(
        default="Seu registro foi enviado para analise.", min_length=1, max_length=2000
    )
    approved_message: str = Field(
        default="Seu registro foi aprovado. Bem-vindo!", min_length=1, max_length=2000
    )
    rejected_message: str = Field(
        default="Seu registro foi rejeitado.", min_length=1, max_length=2000
    )
    log_approved_title: str = Field(
        default="Registro aprovado", min_length=1, max_length=256
    )
    log_rejected_title: str = Field(
        default="Registro rejeitado", min_length=1, max_length=256
    )
    log_footer: str = Field(
        default="Yuno • Sistema de Registro", min_length=1, max_length=2048
    )
    show_member_avatar: bool = True
    approved_dm_title: str = Field(
        default="Registro aprovado", min_length=1, max_length=256
    )
    rejected_dm_title: str = Field(
        default="Registro não aprovado", min_length=1, max_length=256
    )
    already_pending_message: str = Field(
        default="Voce ja possui um registro aguardando analise.", min_length=1, max_length=2000
    )
    already_registered_message: str = Field(
        default="Voce ja possui um registro ativo.", min_length=1, max_length=2000
    )
    duplicate_id_message: str = Field(
        default="Este ID ja esta vinculado a outro membro.", min_length=1, max_length=2000
    )
    resubmit_not_allowed_message: str = Field(
        default="Um novo envio apos rejeicao nao esta permitido.", min_length=1, max_length=2000
    )
    generic_error_message: str = Field(
        default="Nao foi possivel concluir a operacao. Tente novamente.",
        min_length=1,
        max_length=2000,
    )

    @field_validator("approver_role_ids")
    @classmethod
    def unique_roles(cls, value: list[str]) -> list[str]:
        clean = [item.strip() for item in value if item.strip()]
        if any(len(item) > 32 for item in clean):
            raise ValueError("ID de cargo invalido.")
        return list(dict.fromkeys(clean))

    @field_validator("nickname_template")
    @classmethod
    def valid_template(cls, value: str) -> str:
        try:
            return validate_nickname_template(value)
        except RegistrationDomainError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("panel_color")
    @classmethod
    def valid_color(cls, value: str) -> str:
        import re

        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
            raise ValueError("Cor deve usar #RRGGBB.")
        return value.upper()

    @field_validator("panel_banner_url", "panel_thumbnail_url")
    @classmethod
    def valid_optional_url(cls, value: str) -> str:
        if value and not value.startswith(("https://", "http://")):
            raise ValueError("URL deve usar HTTP(S).")
        return value

    @model_validator(mode="after")
    def valid_ranges(self) -> RegistrationConfig:
        if self.player_id_min_length > self.player_id_max_length:
            raise ValueError("Limite minimo do ID excede o maximo.")
        if self.name_min_length > self.name_max_length:
            raise ValueError("Limite minimo do nome excede o maximo.")
        return self


class RegistrationDecisionDeliveryPayload(RegistrationSchema):
    schema_version: Literal[2] = 2
    request_id: str = Field(min_length=1, max_length=36)
    decision: Literal["approved", "rejected"]
    discord_user_id: str = Field(min_length=1, max_length=32)
    submitted_name: str = Field(min_length=1, max_length=120)
    player_id: str = Field(min_length=1, max_length=120)
    reviewed_by: str | None = Field(default=None, max_length=32)
    decision_at: datetime
    reason: str | None = Field(default=None, max_length=1000)
    previous_nickname: str | None = Field(default=None, max_length=32)
    target_nickname: str | None = Field(default=None, max_length=32)
    member_role_id: str = Field(min_length=1, max_length=32)
    role_was_present: bool | None = None
    nickname_applied: bool = False
    role_applied: bool = False
    config_version: int = Field(ge=1)
    log_approved_title: str = Field(min_length=1, max_length=256)
    log_rejected_title: str = Field(min_length=1, max_length=256)
    log_footer: str = Field(min_length=1, max_length=2048)
    show_member_avatar: bool = True
    approved_dm_title: str = Field(min_length=1, max_length=256)
    rejected_dm_title: str = Field(min_length=1, max_length=256)


class RegistrationSubmit(RegistrationSchema):
    name: str = Field(min_length=1, max_length=120)
    player_id: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def normalized_name(cls, value: str) -> str:
        normalized = normalize_name(value)
        if not normalized:
            raise ValueError("Nome obrigatorio.")
        return normalized


class RegistrationSubmitCommand(RegistrationSchema):
    actor: ActorContextIn
    registration: RegistrationSubmit
    panel_config_version: int | None = Field(default=None, ge=1)


class ApprovalClaimCommand(RegistrationSchema):
    actor: ActorContextIn
    operation_token: str | None = Field(default=None, min_length=16, max_length=160)


class ApprovalPreflightCommand(RegistrationSchema):
    actor: ActorContextIn
    operation_token: str = Field(min_length=16, max_length=160)
    previous_nickname: str | None = Field(default=None, max_length=32)
    role_was_present: bool
    target_nickname: str = Field(min_length=1, max_length=32)


class ApprovalStepCommand(RegistrationSchema):
    actor: ActorContextIn
    operation_token: str = Field(min_length=16, max_length=160)
    step: str = Field(pattern=r"^(nickname|role)$")


class ApprovalCompleteCommand(RegistrationSchema):
    actor: ActorContextIn
    operation_token: str = Field(min_length=16, max_length=160)


class ApprovalReleaseCommand(RegistrationSchema):
    actor: ActorContextIn
    operation_token: str = Field(min_length=16, max_length=160)
    compensated: bool
    error_code: str = Field(min_length=1, max_length=120)


class RegistrationRejectCommand(RegistrationSchema):
    actor: ActorContextIn
    reason: str = Field(min_length=1, max_length=1000)


class ReviewMessageCommand(RegistrationSchema):
    actor: ActorContextIn
    channel_id: str = Field(min_length=1, max_length=32)
    message_id: str = Field(min_length=1, max_length=32)


class MemberDeactivateCommand(RegistrationSchema):
    actor: ActorContextIn
