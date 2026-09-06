from datetime import datetime
from uuid import uuid4

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass


from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, JsonType


class LicenseStatus(StrEnum):
    pending = "pending"
    active = "active"
    blocked = "blocked"
    revoked = "revoked"


class RecordStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    open = "open"
    in_progress = "in_progress"
    done = "done"
    cancelled = "cancelled"


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    discord_user_id: Mapped[str | None] = mapped_column(String(32), index=True)
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    name: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    licenses: Mapped[list["License"]] = relationship(back_populates="customer")


class License(Base):
    __tablename__ = "licenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, default=lambda: uuid4().hex, index=True)
    status: Mapped[LicenseStatus] = mapped_column(Enum(LicenseStatus), default=LicenseStatus.pending, index=True)
    guild_id: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    guild_name: Mapped[str | None] = mapped_column(String(120))
    owner_discord_id: Mapped[str | None] = mapped_column(String(32), index=True)
    payment_provider: Mapped[str | None] = mapped_column(String(40))
    payment_reference: Mapped[str | None] = mapped_column(String(120), unique=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    customer: Mapped[Customer | None] = relationship(back_populates="licenses")


class GuildConfig(Base):
    __tablename__ = "guild_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    guild_name: Mapped[str | None] = mapped_column(String(120))
    admin_role_ids: Mapped[list[str]] = mapped_column(JsonType, default=list)
    log_channel_id: Mapped[str | None] = mapped_column(String(32))
    modules: Mapped[dict] = mapped_column(JsonType, default=dict)
    command_permissions: Mapped[dict] = mapped_column(JsonType, default=dict)
    messages: Mapped[dict] = mapped_column(JsonType, default=dict)
    settings: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ModuleConfigState(Base):
    __tablename__ = "module_config_states"
    __table_args__ = (
        UniqueConstraint("guild_id", "module_key", name="uq_module_config_states_guild_module"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    module_key: Mapped[str] = mapped_column(String(40), index=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    draft_data: Mapped[dict] = mapped_column(JsonType, default=dict, server_default=text("'{}'"))
    published_data: Mapped[dict] = mapped_column(JsonType, default=dict, server_default=text("'{}'"))
    draft_revision: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    published_revision: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    draft_updated_by: Mapped[str | None] = mapped_column(String(32), index=True)
    draft_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[str | None] = mapped_column(String(32), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("guild_id", "name", name="uq_products_guild_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(120))
    unit: Mapped[str] = mapped_column(String(40), default="unidade")
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SystemRecord(Base):
    __tablename__ = "system_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    module: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[RecordStatus] = mapped_column(Enum(RecordStatus), default=RecordStatus.pending, index=True)
    title: Mapped[str] = mapped_column(String(160))
    requester_id: Mapped[str] = mapped_column(String(32), index=True)
    reviewer_id: Mapped[str | None] = mapped_column(String(32), index=True)
    channel_id: Mapped[str | None] = mapped_column(String(32), index=True)
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str | None] = mapped_column(String(32), index=True)
    actor_id: Mapped[str | None] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str | None] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class PaymentEvent(Base):
    __tablename__ = "payment_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    reference: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    raw_payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ParceriaConfig(Base):
    __tablename__ = "parceria_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    category_id: Mapped[str | None] = mapped_column(String(32))
    registrar_channel_id: Mapped[str] = mapped_column(String(32))
    ativas_channel_id: Mapped[str] = mapped_column(String(32))
    panel_message_id: Mapped[str | None] = mapped_column(String(32))


class Parceria(Base):
    __tablename__ = "parcerias"
    __table_args__ = (UniqueConstraint("guild_id", "nome_familia_normalizado", name="uq_parcerias_guild_nome"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    nome_familia: Mapped[str] = mapped_column(String(100))
    # Postgres nao tem COLLATE NOCASE; a coluna normalizada e o que garante
    # unicidade e busca sem diferenciar maiusculas em ambos os dialetos.
    nome_familia_normalizado: Mapped[str] = mapped_column(String(100), index=True)
    produto: Mapped[str] = mapped_column(String(100))
    contato_01: Mapped[str | None] = mapped_column(String(150))
    contato_02: Mapped[str | None] = mapped_column(String(150))
    mensagem_lista_id: Mapped[str] = mapped_column(String(32))
    nome_arquivo_imagem: Mapped[str] = mapped_column(String(255))
    registrado_por: Mapped[str] = mapped_column(String(32))
    ativo: Mapped[bool] = mapped_column(default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Setado explicitamente em app/parceria.py, nao via onupdate=func.now():
    # ler esse valor de volta na mesma resposta (como o cliente HTTP do bot
    # precisa) dispara um refresh lazy fora do contexto async do SQLAlchemy.
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Ausencia(Base):
    __tablename__ = "ausencias"

    guild_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    nome: Mapped[str | None] = mapped_column(String(120))
    dias: Mapped[int] = mapped_column(Integer)
    motivo: Mapped[str] = mapped_column(Text)
    inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fim: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    avisado: Mapped[int] = mapped_column(Integer, default=0, index=True)
    message_id: Mapped[str | None] = mapped_column(String(32))


# Registra as tabelas transversais novas no mesmo Base sem misturar seus
# conceitos com os modelos legados deste arquivo.
from app.domain_modules.farm_tickets import (
    models as farm_ticket_v2_models,  # noqa: F401
)
from app.domain_modules.meta import models as meta_domain_models  # noqa: F401
from app.domain_modules.registration import (
    models as registration_domain_models,  # noqa: F401
)
from app.domain_modules.tags import models as tags_domain_models  # noqa: F401
from app.domain_modules.parceria import models as parceria_domain_models  # noqa: F401
from app.platform import models as platform_models  # noqa: F401
