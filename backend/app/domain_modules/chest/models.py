from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, JsonType
from app.domain_modules.chest.domain import MovementType


def new_id() -> str:
    return str(uuid4())


class Chest(Base):
    __tablename__ = "chest_chests"
    __table_args__ = (
        UniqueConstraint("guild_id", "id", name="uq_chest_chests_guild_id"),
        Index("ix_chest_chests_guild", "guild_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ChestItem(Base):
    __tablename__ = "chest_items"
    __table_args__ = (
        UniqueConstraint("guild_id", "id", name="uq_chest_items_guild_id"),
        Index("ix_chest_items_guild", "guild_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ChestDraftChest(Base):
    __tablename__ = "chest_draft_chests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["draft_id"], ["module_config_drafts.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["guild_id", "chest_id"],
            ["chest_chests.guild_id", "chest_chests.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("draft_id", "chest_id", name="uq_chest_draft_chest_identity"),
        UniqueConstraint(
            "draft_id", "name_normalized", name="uq_chest_draft_chest_name"
        ),
        UniqueConstraint(
            "draft_id",
            "guild_id",
            "chest_id",
            name="uq_chest_draft_chest_tenant_identity",
        ),
        Index("ix_chest_draft_chests_guild", "guild_id", "draft_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    draft_id: Mapped[int] = mapped_column(Integer, nullable=False)
    guild_id: Mapped[str] = mapped_column(String(32), nullable=False)
    chest_id: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(100), nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    position: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))


class ChestDraftItem(Base):
    __tablename__ = "chest_draft_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["draft_id"], ["module_config_drafts.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["guild_id", "item_id"],
            ["chest_items.guild_id", "chest_items.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("draft_id", "item_id", name="uq_chest_draft_item_identity"),
        UniqueConstraint(
            "draft_id", "name_normalized", name="uq_chest_draft_item_name"
        ),
        UniqueConstraint(
            "draft_id",
            "guild_id",
            "item_id",
            name="uq_chest_draft_item_tenant_identity",
        ),
        Index("ix_chest_draft_items_guild", "guild_id", "draft_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    draft_id: Mapped[int] = mapped_column(Integer, nullable=False)
    guild_id: Mapped[str] = mapped_column(String(32), nullable=False)
    item_id: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(100), nullable=False)
    unit: Mapped[str] = mapped_column(
        String(40), nullable=False, default="unidade", server_default="unidade"
    )
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    position: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))


class ChestDraftLink(Base):
    __tablename__ = "chest_draft_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["draft_id", "guild_id", "chest_id"],
            [
                "chest_draft_chests.draft_id",
                "chest_draft_chests.guild_id",
                "chest_draft_chests.chest_id",
            ],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["draft_id", "guild_id", "item_id"],
            [
                "chest_draft_items.draft_id",
                "chest_draft_items.guild_id",
                "chest_draft_items.item_id",
            ],
            ondelete="CASCADE",
        ),
        UniqueConstraint("draft_id", "chest_id", "item_id", name="uq_chest_draft_link"),
        Index("ix_chest_draft_links_guild", "guild_id", "draft_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    draft_id: Mapped[int] = mapped_column(Integer, nullable=False)
    guild_id: Mapped[str] = mapped_column(String(32), nullable=False)
    chest_id: Mapped[str] = mapped_column(String(36), nullable=False)
    item_id: Mapped[str] = mapped_column(String(36), nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )


class ChestVersionChest(Base):
    __tablename__ = "chest_version_chests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["config_version_id"], ["module_config_versions.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["guild_id", "chest_id"],
            ["chest_chests.guild_id", "chest_chests.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "config_version_id", "chest_id", name="uq_chest_version_chest_identity"
        ),
        UniqueConstraint(
            "config_version_id", "name_normalized", name="uq_chest_version_chest_name"
        ),
        UniqueConstraint(
            "config_version_id",
            "guild_id",
            "chest_id",
            name="uq_chest_version_chest_tenant_identity",
        ),
        Index("ix_chest_version_chests_guild", "guild_id", "config_version_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    config_version_id: Mapped[int] = mapped_column(Integer, nullable=False)
    guild_id: Mapped[str] = mapped_column(String(32), nullable=False)
    chest_id: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(100), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class ChestVersionItem(Base):
    __tablename__ = "chest_version_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["config_version_id"], ["module_config_versions.id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["guild_id", "item_id"],
            ["chest_items.guild_id", "chest_items.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "config_version_id", "item_id", name="uq_chest_version_item_identity"
        ),
        UniqueConstraint(
            "config_version_id", "name_normalized", name="uq_chest_version_item_name"
        ),
        UniqueConstraint(
            "config_version_id",
            "guild_id",
            "item_id",
            name="uq_chest_version_item_tenant_identity",
        ),
        Index("ix_chest_version_items_guild", "guild_id", "config_version_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    config_version_id: Mapped[int] = mapped_column(Integer, nullable=False)
    guild_id: Mapped[str] = mapped_column(String(32), nullable=False)
    item_id: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(100), nullable=False)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class ChestVersionLink(Base):
    __tablename__ = "chest_version_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["config_version_id", "guild_id", "chest_id"],
            [
                "chest_version_chests.config_version_id",
                "chest_version_chests.guild_id",
                "chest_version_chests.chest_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["config_version_id", "guild_id", "item_id"],
            [
                "chest_version_items.config_version_id",
                "chest_version_items.guild_id",
                "chest_version_items.item_id",
            ],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "config_version_id", "chest_id", "item_id", name="uq_chest_version_link"
        ),
        Index(
            "ix_chest_version_links_lookup",
            "guild_id",
            "config_version_id",
            "chest_id",
            "active",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    config_version_id: Mapped[int] = mapped_column(Integer, nullable=False)
    guild_id: Mapped[str] = mapped_column(String(32), nullable=False)
    chest_id: Mapped[str] = mapped_column(String(36), nullable=False)
    item_id: Mapped[str] = mapped_column(String(36), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)


class ChestBalance(Base):
    __tablename__ = "chest_balances"
    __table_args__ = (
        ForeignKeyConstraint(
            ["guild_id", "chest_id"],
            ["chest_chests.guild_id", "chest_chests.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["guild_id", "item_id"],
            ["chest_items.guild_id", "chest_items.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("quantity >= 0", name="ck_chest_balance_nonnegative"),
        CheckConstraint("sequence >= 0", name="ck_chest_balance_sequence"),
        UniqueConstraint(
            "guild_id", "chest_id", "item_id", name="uq_chest_balance_identity"
        ),
        UniqueConstraint("guild_id", "id", name="uq_chest_balance_guild_id"),
        UniqueConstraint(
            "guild_id",
            "id",
            "chest_id",
            "item_id",
            name="uq_chest_balance_full_identity",
        ),
        Index("ix_chest_balances_guild_chest", "guild_id", "chest_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), nullable=False)
    chest_id: Mapped[str] = mapped_column(String(36), nullable=False)
    item_id: Mapped[str] = mapped_column(String(36), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(20, 3), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    sequence: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ChestMovement(Base):
    __tablename__ = "chest_movements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["guild_id", "balance_id"],
            ["chest_balances.guild_id", "chest_balances.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["guild_id", "balance_id", "chest_id", "item_id"],
            [
                "chest_balances.guild_id",
                "chest_balances.id",
                "chest_balances.chest_id",
                "chest_balances.item_id",
            ],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["guild_id", "chest_id"],
            ["chest_chests.guild_id", "chest_chests.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["guild_id", "item_id"],
            ["chest_items.guild_id", "chest_items.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint("quantity > 0", name="ck_chest_movement_positive"),
        CheckConstraint(
            "balance_before >= 0 AND balance_after >= 0",
            name="ck_chest_movement_balances",
        ),
        CheckConstraint("sequence > 0", name="ck_chest_movement_sequence"),
        CheckConstraint(
            "(movement_type IN ('DEPOSIT', 'ADJUSTMENT_CREDIT') AND balance_after = balance_before + quantity) OR "
            "(movement_type IN ('WITHDRAWAL', 'ADJUSTMENT_DEBIT') AND balance_after = balance_before - quantity)",
            name="ck_chest_movement_arithmetic",
        ),
        UniqueConstraint(
            "guild_id", "idempotency_key", name="uq_chest_movement_idempotency"
        ),
        UniqueConstraint(
            "balance_id", "sequence", name="uq_chest_movement_balance_sequence"
        ),
        Index("ix_chest_movements_history", "guild_id", "chest_id", "created_at"),
        Index("ix_chest_movements_actor", "guild_id", "actor_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), nullable=False)
    balance_id: Mapped[str] = mapped_column(String(36), nullable=False)
    chest_id: Mapped[str] = mapped_column(String(36), nullable=False)
    item_id: Mapped[str] = mapped_column(String(36), nullable=False)
    movement_type: Mapped[MovementType] = mapped_column(
        Enum(MovementType, native_enum=False, length=24), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 3), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="user", server_default="user"
    )
    balance_before: Mapped[Decimal] = mapped_column(Numeric(20, 3), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(20, 3), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    observation: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    origin: Mapped[str] = mapped_column(
        String(64), nullable=False, default="discord", server_default="discord"
    )
    chest_name_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    item_name_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    unit_snapshot: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ChestCommandReceipt(Base):
    __tablename__ = "chest_command_receipts"
    __table_args__ = (
        UniqueConstraint(
            "guild_id", "idempotency_key", name="uq_chest_command_receipt_idempotency"
        ),
        Index("ix_chest_command_receipts_guild_action", "guild_id", "action"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str] = mapped_column(
        String(80), nullable=False, default="", server_default=""
    )
    result: Mapped[dict] = mapped_column(
        JsonType, nullable=False, default=dict, server_default=text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
