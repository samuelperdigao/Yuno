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
    "adv",
    "anuncio",
    "hierarquia",
    "membros",
    "acao",
    "mod",
    "disparo",
]


def default_modules() -> dict[str, bool]:
    return {module: True for module in MODULES}


class LicenseActivateIn(BaseModel):
    license_key: str = Field(min_length=8)
    guild_id: str
    guild_name: str | None = None
    owner_discord_id: str


class LicenseIssueIn(BaseModel):
    reference: str | None = Field(default=None, max_length=120)
    customer_name: str | None = Field(default=None, max_length=120)
    customer_email: str | None = Field(default=None, max_length=255)
    customer_discord_user_id: str | None = Field(default=None, max_length=32)


class LicenseOut(BaseModel):
    key: str
    status: LicenseStatus
    guild_id: str | None = None
    guild_name: str | None = None
    activated_at: datetime | None = None


class LicenseAdminOut(LicenseOut):
    owner_discord_id: str | None = None
    payment_provider: str | None = None
    payment_reference: str | None = None
    created_at: datetime


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


class ModuleConfigStateOut(BaseModel):
    guild_id: str
    module_key: str
    schema_version: int
    draft_data: dict[str, Any] = Field(default_factory=dict)
    published_data: dict[str, Any] = Field(default_factory=dict)
    draft_revision: int
    published_revision: int
    draft_updated_by: str | None = None
    draft_updated_at: datetime | None = None
    published_by: str | None = None
    published_at: datetime | None = None


class ModuleConfigDraftIn(BaseModel):
    expected_revision: int = Field(ge=0)
    schema_version: int = Field(ge=1)
    draft_data: dict[str, Any]


class ModuleConfigProjectionIn(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)
    messages: dict[str, Any] = Field(default_factory=dict)
    command_permissions: dict[str, Any] = Field(default_factory=dict)
    enabled: bool | None = None


class ModuleConfigPublishIn(BaseModel):
    expected_revision: int = Field(ge=0)
    schema_version: int = Field(ge=1)
    projection: ModuleConfigProjectionIn
    panel_refs: dict[str, Any] = Field(default_factory=dict)


class RevisionConflictDetail(BaseModel):
    detail: str
    expected_revision: int
    current_revision: int


class RevisionConflictOut(BaseModel):
    detail: RevisionConflictDetail


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
