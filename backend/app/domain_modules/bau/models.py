from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.platform.correlation import CORRELATION_ID_MAX_LENGTH


def new_id() -> str:
    return str(uuid4())


class BauCategory(Base):
    """Categoria de produtos do baú, configurável por guild."""

    __tablename__ = "bau_categories"
    __table_args__ = (
        UniqueConstraint("guild_id", "name", name="uq_bau_categories_guild_name"),
        Index("ix_bau_categories_guild_position", "guild_id", "position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(60))
    position: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BauItem(Base):
    """Produto do catálogo do baú. O nome é único por guild para permitir
    localizar o item sem depender da categoria (movimentação em lote)."""

    __tablename__ = "bau_items"
    __table_args__ = (
        UniqueConstraint("guild_id", "name", name="uq_bau_items_guild_name"),
        Index("ix_bau_items_guild_category", "guild_id", "category_id", "position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    category_id: Mapped[str] = mapped_column(
        ForeignKey("bau_categories.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    position: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BauStock(Base):
    """Estoque atual de um item. Uma linha por item; `generation` é o contador
    otimista incrementado a cada escrita, usado para detectar corrida entre
    duas movimentações concorrentes."""

    __tablename__ = "bau_stock"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_bau_stock_quantity_non_negative"),
    )

    item_id: Mapped[str] = mapped_column(
        ForeignKey("bau_items.id", ondelete="CASCADE"), primary_key=True
    )
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    generation: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    updated_by: Mapped[str | None] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BauMovement(Base):
    """Histórico imutável de toda alteração de estoque."""

    __tablename__ = "bau_movements"
    __table_args__ = (
        Index("ix_bau_movements_guild_item_created", "guild_id", "item_id", "created_at"),
        Index("ix_bau_movements_guild_created", "guild_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    item_id: Mapped[str | None] = mapped_column(
        ForeignKey("bau_items.id", ondelete="SET NULL"), index=True
    )
    item_name: Mapped[str] = mapped_column(String(80))
    actor_id: Mapped[str] = mapped_column(String(32), index=True)
    operation: Mapped[str] = mapped_column(String(20))
    quantity_delta: Mapped[int] = mapped_column(Integer)
    quantity_before: Mapped[int] = mapped_column(Integer)
    quantity_after: Mapped[int] = mapped_column(Integer)
    generation_after: Mapped[int] = mapped_column(Integer)
    correlation_id: Mapped[str] = mapped_column(String(CORRELATION_ID_MAX_LENGTH), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
