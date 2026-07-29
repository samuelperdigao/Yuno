from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models import LicenseStatus, RecordStatus


MODULES = [
    "set",
    "meta",
    "ticket",
    "farm_tickets",
    "parceria",
    "encomenda",
    "ausencia",
    "radio",
    "producao",
    "adv",
    "anuncio",
    "hierarquia",
    "membros",
    "acao",
    "mod",
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


class AusenciaUpsertIn(BaseModel):
    user_id: str
    nome: str | None = None
    dias: int = Field(ge=1, le=7)
    motivo: str = Field(default="Não informado", max_length=300)
    inicio: datetime
    fim: datetime


class AusenciaMessagePatch(BaseModel):
    message_id: str | None = None


class AusenciaOut(BaseModel):
    guild_id: str
    user_id: str
    nome: str | None = None
    dias: int
    motivo: str
    inicio: datetime
    fim: datetime
    avisado: int = 0
    message_id: str | None = None


class ParceriaConfigIn(BaseModel):
    category_id: str | None = None
    registrar_channel_id: str
    ativas_channel_id: str
    panel_message_id: str | None = None


class ParceriaConfigOut(ParceriaConfigIn):
    guild_id: str


class ParceriaCreateIn(BaseModel):
    nome_familia: str
    produto: str
    contato_01: str | None = None
    contato_02: str | None = None
    mensagem_lista_id: str
    nome_arquivo_imagem: str
    registrado_por: str


class ParceriaUpdateIn(BaseModel):
    nome_familia: str
    produto: str
    contato_01: str | None = None
    contato_02: str | None = None


class ParceriaImagePatch(BaseModel):
    nome_arquivo_imagem: str


class ParceriaOut(BaseModel):
    id: int
    guild_id: str
    nome_familia: str
    produto: str
    contato_01: str | None = None
    contato_02: str | None = None
    mensagem_lista_id: str
    nome_arquivo_imagem: str
    registrado_por: str
    ativo: bool
    criado_em: datetime
    atualizado_em: datetime | None = None


class FarmTicketConfigIn(BaseModel):
    category_ids: list[str] = Field(default_factory=list)
    admin_role_ids: list[str] = Field(default_factory=list)
    log_channel_id: str
    panel_channel_id: str
    folders_category_id: str | None = None
    participant_role_ids: list[str] = Field(default_factory=list)


class FarmTicketConfigOut(FarmTicketConfigIn):
    guild_id: str


class FarmWeeklyGoalIn(BaseModel):
    week_id: str
    items: list[dict[str, Any]] = Field(min_length=1, max_length=5)
    created_by: str | None = None


class FarmWeeklyGoalOut(FarmWeeklyGoalIn):
    id: int
    guild_id: str
    active: bool
    created_at: datetime


class FarmTicketReserveIn(BaseModel):
    week_id: str
    user_id: str
    member_name: str
    open_payload: dict[str, Any] = Field(default_factory=dict)
    folder_channel_id: str | None = None
    folder_slot: int | None = None
    game_id: str | None = None
    folder_nickname: str | None = None


class FarmTicketChannelPatch(BaseModel):
    channel_id: str
    panel_message_id: str | None = None
    status: str = "aberto"


class FarmTicketEntryIn(BaseModel):
    actor_id: str
    values: dict[str, int]
    proof_channel_id: str
    proof_message_id: str
    proof_url: str
    observacao: str | None = None


class FarmTicketActionIn(BaseModel):
    actor_id: str | None = None
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)


class FarmTicketReviewIn(BaseModel):
    actor_id: str
    entry_id: int
    reason: str


class FarmTicketFinalizeIn(BaseModel):
    actor_id: str | None = None
    reason: str


class FarmTicketApproveIn(BaseModel):
    actor_id: str


class FarmTicketActionLogPatch(BaseModel):
    log_message_id: str | None = None


class FarmTicketEntryOut(BaseModel):
    id: int
    ticket_id: int
    guild_id: str
    values: dict[str, int]
    proof_channel_id: str
    proof_message_id: str
    proof_url: str
    log_proof_url: str | None = None
    observacao: str | None = None
    status: str
    reviewed_by: str | None = None
    review_reason: str | None = None
    created_at: datetime


class FarmTicketOut(BaseModel):
    id: int
    guild_id: str
    week_id: str
    user_id: str
    member_name: str
    folder_channel_id: str | None = None
    folder_slot: int | None = None
    game_id: str | None = None
    folder_nickname: str | None = None
    channel_id: str | None = None
    panel_message_id: str | None = None
    status: str
    assigned_to: str | None = None
    goal_items: list[dict[str, Any]]
    progress: dict[str, Any]
    created_at: datetime
    finalized_at: datetime | None = None
    finalized_by: str | None = None
    finalization_reason: str | None = None
    deleted_at: datetime | None = None
    entries: list[FarmTicketEntryOut] = Field(default_factory=list)


class FarmTicketReserveOut(BaseModel):
    ticket: FarmTicketOut
    existing: bool = False


class FarmTicketActionOut(BaseModel):
    id: int
    ticket_id: int | None = None
    guild_id: str
    action: str
    actor_id: str | None = None
    event_id: str | None = None
    payload: dict[str, Any]
    created_at: datetime
    log_sent_at: datetime | None = None
    log_message_id: str | None = None
    log_attempts: int
