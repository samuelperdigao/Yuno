from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
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
from app.domain_modules.farm_tickets.domain import (
    BindingOwnership,
    BindingState,
    EntryRevisionStatus,
    FormKind,
    ObjectiveKind,
    OperationKind,
    OperationStatus,
    ProofCandidateStatus,
    ProofStorageState,
    ResourceKind,
    ResourceRemovalReason,
    TicketCloseReason,
    TicketStatus,
)


def new_id() -> str:
    return str(uuid4())


class FarmTicket(Base):
    __tablename__ = "farm_ticket_v2_tickets"
    __table_args__ = (
        UniqueConstraint(
            "guild_id", "meta_cycle_id", "member_id", name="uq_ftv2_ticket_history"
        ),
        Index(
            "uq_ftv2_active_member_binding",
            "guild_id",
            "member_id",
            unique=True,
            postgresql_where=text("binding_released_at IS NULL"),
            sqlite_where=text("binding_released_at IS NULL"),
        ),
        CheckConstraint("revision > 0", name="ck_ftv2_ticket_revision"),
        CheckConstraint(
            "(status = 'IN_PROGRESS' AND result_finalized_at IS NULL) OR "
            "(status <> 'IN_PROGRESS' AND result_finalized_at IS NOT NULL)",
            name="ck_ftv2_ticket_result_finalized",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    member_id: Mapped[str] = mapped_column(String(32), index=True)
    meta_goal_id: Mapped[int] = mapped_column(BigInteger, index=True)
    meta_cycle_id: Mapped[int] = mapped_column(BigInteger, index=True)
    registration_identity_id: Mapped[str] = mapped_column(String(36))
    member_name: Mapped[str] = mapped_column(String(120))
    player_id: Mapped[str] = mapped_column(String(120))
    base_nickname: Mapped[str] = mapped_column(String(120))
    status: Mapped[TicketStatus] = mapped_column(
        Enum(TicketStatus, native_enum=False, length=32),
        default=TicketStatus.IN_PROGRESS,
        server_default=text("'IN_PROGRESS'"),
        index=True,
    )
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    assigned_admin_id: Mapped[str | None] = mapped_column(String(32), index=True)
    operations_closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    withdrawals_open: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    settlement_closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    binding_released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    member_left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_finalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    close_reason: Mapped[TicketCloseReason | None] = mapped_column(
        Enum(TicketCloseReason, native_enum=False, length=32)
    )
    last_resource_removal_reason: Mapped[ResourceRemovalReason | None] = mapped_column(
        Enum(ResourceRemovalReason, native_enum=False, length=32)
    )
    frozen_launched_total: Mapped[Decimal | None] = mapped_column(Numeric(20, 3))
    frozen_withdrawn_total: Mapped[Decimal | None] = mapped_column(Numeric(20, 3))
    frozen_unwithdrawn_total: Mapped[Decimal | None] = mapped_column(Numeric(20, 3))
    frozen_totals: Mapped[dict | None] = mapped_column(JsonType)
    provisioning_error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FarmTicketCycle(Base):
    __tablename__ = "farm_ticket_v2_cycles"
    __table_args__ = (
        UniqueConstraint("ticket_id", name="uq_ftv2_cycle_ticket"),
        CheckConstraint("ends_at > starts_at", name="ck_ftv2_cycle_dates"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE"), index=True
    )
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    meta_goal_id: Mapped[int] = mapped_column(BigInteger, index=True)
    meta_cycle_id: Mapped[int] = mapped_column(BigInteger, index=True)
    goal_name: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(64))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    participation_ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    event_sequence_at_open: Mapped[int | None] = mapped_column(BigInteger)


class FarmTicketObjective(Base):
    __tablename__ = "farm_ticket_v2_objectives"
    __table_args__ = (
        UniqueConstraint(
            "ticket_id", "meta_objective_id", name="uq_ftv2_ticket_objective"
        ),
        UniqueConstraint("ticket_id", "position", name="uq_ftv2_objective_position"),
        CheckConstraint("target_amount > 0", name="ck_ftv2_objective_target"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE"), index=True
    )
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    meta_objective_id: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[ObjectiveKind] = mapped_column(
        Enum(ObjectiveKind, native_enum=False, length=10)
    )
    name: Mapped[str] = mapped_column(String(100))
    unit: Mapped[str | None] = mapped_column(String(30))
    target_amount: Mapped[Decimal] = mapped_column(Numeric(20, 3))
    position: Mapped[int] = mapped_column(Integer)


class FarmTicketEntry(Base):
    __tablename__ = "farm_ticket_v2_entries"
    __table_args__ = (
        UniqueConstraint("ticket_id", "number", name="uq_ftv2_entry_number"),
        CheckConstraint("number > 0", name="ck_ftv2_entry_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE"), index=True
    )
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    number: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[str] = mapped_column(String(32))
    current_revision: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FarmTicketEntryRevision(Base):
    __tablename__ = "farm_ticket_v2_entry_revisions"
    __table_args__ = (
        UniqueConstraint("entry_id", "version", name="uq_ftv2_entry_revision"),
        CheckConstraint("version > 0", name="ck_ftv2_entry_revision_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("farm_ticket_v2_entries.id", ondelete="CASCADE"), index=True
    )
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE"), index=True
    )
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[EntryRevisionStatus] = mapped_column(
        Enum(EntryRevisionStatus, native_enum=False, length=16),
        default=EntryRevisionStatus.PENDING,
        server_default=text("'PENDING'"),
    )
    actor_id: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FarmTicketEntryItem(Base):
    __tablename__ = "farm_ticket_v2_entry_items"
    __table_args__ = (
        UniqueConstraint(
            "revision_id", "objective_id", name="uq_ftv2_entry_item_objective"
        ),
        CheckConstraint("amount > 0", name="ck_ftv2_entry_item_amount"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("farm_ticket_v2_entry_revisions.id", ondelete="CASCADE"), index=True
    )
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("farm_ticket_v2_entries.id", ondelete="CASCADE"), index=True
    )
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE"), index=True
    )
    objective_id: Mapped[str] = mapped_column(
        ForeignKey("farm_ticket_v2_objectives.id", ondelete="RESTRICT"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 3))


class FarmTicketPendingOperation(Base):
    __tablename__ = "farm_ticket_v2_pending_operations"
    __table_args__ = (
        UniqueConstraint(
            "guild_id", "idempotency_key", name="uq_ftv2_operation_idempotency"
        ),
        Index(
            "uq_ftv2_active_operation",
            "ticket_id",
            unique=True,
            postgresql_where=text(
                "status IN ('AWAITING_PROOF','PROOF_CLAIMED','PROCESSING_PROOF','RETRYING_PROOF')"
            ),
            sqlite_where=text(
                "status IN ('AWAITING_PROOF','PROOF_CLAIMED','PROCESSING_PROOF','RETRYING_PROOF')"
            ),
        ),
        Index(
            "uq_ftv2_proof_message",
            "guild_id",
            "proof_message_id",
            unique=True,
            postgresql_where=text("proof_message_id IS NOT NULL"),
            sqlite_where=text("proof_message_id IS NOT NULL"),
        ),
        Index(
            "uq_ftv2_operation_interaction",
            "guild_id",
            "interaction_id",
            unique=True,
            postgresql_where=text("interaction_id IS NOT NULL"),
            sqlite_where=text("interaction_id IS NOT NULL"),
        ),
        CheckConstraint(
            "proof_deadline > created_at", name="ck_ftv2_operation_deadline"
        ),
        CheckConstraint("attempts >= 0", name="ck_ftv2_operation_attempts"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE"), index=True
    )
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[OperationKind] = mapped_column(
        Enum(OperationKind, native_enum=False, length=20)
    )
    status: Mapped[OperationStatus] = mapped_column(
        Enum(OperationStatus, native_enum=False, length=24), index=True
    )
    target_entry_id: Mapped[str | None] = mapped_column(
        ForeignKey("farm_ticket_v2_entries.id", ondelete="RESTRICT"), index=True
    )
    pending_entry_id: Mapped[str] = mapped_column(
        ForeignKey("farm_ticket_v2_entries.id", ondelete="CASCADE"), index=True
    )
    pending_revision_id: Mapped[str] = mapped_column(
        ForeignKey("farm_ticket_v2_entry_revisions.id", ondelete="CASCADE"), unique=True
    )
    actor_id: Mapped[str] = mapped_column(String(32), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(180))
    interaction_id: Mapped[str | None] = mapped_column(String(32))
    proof_deadline: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    claim_token: Mapped[str | None] = mapped_column(String(72), unique=True)
    proof_message_id: Mapped[str | None] = mapped_column(String(32))
    proof_attachment_id: Mapped[str | None] = mapped_column(String(32))
    proof_author_id: Mapped[str | None] = mapped_column(String(32))
    proof_channel_id: Mapped[str | None] = mapped_column(String(32))
    proof_received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attachment_filename: Mapped[str | None] = mapped_column(String(255))
    attachment_content_type: Mapped[str | None] = mapped_column(String(100))
    attachment_size: Mapped[int | None] = mapped_column(BigInteger)
    attachment_url: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    processing_error: Mapped[str | None] = mapped_column(Text)
    failed_recoverably: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FarmTicketProofCandidate(Base):
    __tablename__ = "farm_ticket_v2_proof_candidates"
    __table_args__ = (
        UniqueConstraint("guild_id", "message_id", name="uq_ftv2_candidate_message"),
        UniqueConstraint(
            "guild_id", "attachment_id", name="uq_ftv2_candidate_attachment"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    operation_id: Mapped[str] = mapped_column(
        ForeignKey("farm_ticket_v2_pending_operations.id", ondelete="CASCADE"),
        index=True,
    )
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE"), index=True
    )
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    message_id: Mapped[str] = mapped_column(String(32))
    attachment_id: Mapped[str] = mapped_column(String(32))
    author_id: Mapped[str] = mapped_column(String(32))
    channel_id: Mapped[str] = mapped_column(String(32))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    source_url: Mapped[str] = mapped_column(Text)
    claim_token: Mapped[str] = mapped_column(String(72), unique=True)
    status: Mapped[ProofCandidateStatus] = mapped_column(
        Enum(ProofCandidateStatus, native_enum=False, length=12),
        default=ProofCandidateStatus.CLAIMED,
        server_default=text("'CLAIMED'"),
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FarmTicketProof(Base):
    __tablename__ = "farm_ticket_v2_proofs"
    __table_args__ = (
        UniqueConstraint("operation_id", name="uq_ftv2_proof_operation"),
        UniqueConstraint("guild_id", "message_id", name="uq_ftv2_proof_message_stored"),
        UniqueConstraint("object_key", name="uq_ftv2_proof_object_key"),
        CheckConstraint(
            "size_bytes > 0 AND size_bytes <= 20971520", name="ck_ftv2_proof_size"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    operation_id: Mapped[str] = mapped_column(
        ForeignKey("farm_ticket_v2_pending_operations.id", ondelete="RESTRICT"),
        index=True,
    )
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE"), index=True
    )
    entry_revision_id: Mapped[str] = mapped_column(
        ForeignKey("farm_ticket_v2_entry_revisions.id", ondelete="RESTRICT"),
        unique=True,
    )
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    message_id: Mapped[str] = mapped_column(String(32))
    attachment_id: Mapped[str] = mapped_column(String(32))
    author_id: Mapped[str] = mapped_column(String(32))
    channel_id: Mapped[str] = mapped_column(String(32))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    object_key: Mapped[str] = mapped_column(String(500))
    checksum_sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    content_type: Mapped[str] = mapped_column(String(100))
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_state: Mapped[ProofStorageState] = mapped_column(
        Enum(ProofStorageState, native_enum=False, length=20),
        default=ProofStorageState.STORED,
        server_default=text("'STORED'"),
    )
    thread_delivery_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    cleanup_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FarmTicketWithdrawal(Base):
    __tablename__ = "farm_ticket_v2_withdrawals"
    __table_args__ = (
        UniqueConstraint("ticket_id", "number", name="uq_ftv2_withdrawal_number"),
        UniqueConstraint(
            "guild_id", "idempotency_key", name="uq_ftv2_withdrawal_idempotency"
        ),
        CheckConstraint("number > 0", name="ck_ftv2_withdrawal_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE"), index=True
    )
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    number: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[str] = mapped_column(String(32))
    idempotency_key: Mapped[str] = mapped_column(String(180))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FarmTicketWithdrawalItem(Base):
    __tablename__ = "farm_ticket_v2_withdrawal_items"
    __table_args__ = (
        UniqueConstraint(
            "withdrawal_id", "objective_id", name="uq_ftv2_withdrawal_objective"
        ),
        CheckConstraint("amount > 0", name="ck_ftv2_withdrawal_item_amount"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    withdrawal_id: Mapped[str] = mapped_column(
        ForeignKey("farm_ticket_v2_withdrawals.id", ondelete="CASCADE"), index=True
    )
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE"), index=True
    )
    objective_id: Mapped[str] = mapped_column(
        ForeignKey("farm_ticket_v2_objectives.id", ondelete="RESTRICT"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 3))


class FarmTicketAllocation(Base):
    __tablename__ = "farm_ticket_v2_allocations"
    __table_args__ = (
        UniqueConstraint(
            "withdrawal_item_id", "entry_item_id", name="uq_ftv2_allocation_pair"
        ),
        CheckConstraint("amount > 0", name="ck_ftv2_allocation_amount"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE"), index=True
    )
    objective_id: Mapped[str] = mapped_column(
        ForeignKey("farm_ticket_v2_objectives.id", ondelete="RESTRICT"), index=True
    )
    withdrawal_item_id: Mapped[str] = mapped_column(
        ForeignKey("farm_ticket_v2_withdrawal_items.id", ondelete="CASCADE"), index=True
    )
    entry_item_id: Mapped[str] = mapped_column(
        ForeignKey("farm_ticket_v2_entry_items.id", ondelete="RESTRICT"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 3))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FarmTicketEvent(Base):
    __tablename__ = "farm_ticket_v2_events"
    __table_args__ = (
        UniqueConstraint("ticket_id", "sequence", name="uq_ftv2_event_sequence"),
        UniqueConstraint(
            "guild_id", "deduplication_key", name="uq_ftv2_event_deduplication"
        ),
        CheckConstraint("sequence > 0", name="ck_ftv2_event_sequence"),
        Index("ix_ftv2_event_read", "ticket_id", "sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE"), index=True
    )
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    sequence: Mapped[int] = mapped_column(BigInteger)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    actor_id: Mapped[str | None] = mapped_column(String(32))
    deduplication_key: Mapped[str] = mapped_column(String(180))
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FarmTicketDiscordBinding(Base):
    __tablename__ = "farm_ticket_v2_discord_bindings"
    __table_args__ = (
        UniqueConstraint(
            "guild_id",
            "kind",
            "resource_id",
            name="uq_ftv2_binding_resource_kind",
        ),
        UniqueConstraint("ticket_id", "kind", name="uq_ftv2_ticket_binding_kind"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ticket_id: Mapped[str | None] = mapped_column(
        ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE"), index=True
    )
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[ResourceKind] = mapped_column(
        Enum(ResourceKind, native_enum=False, length=32)
    )
    resource_id: Mapped[str] = mapped_column(String(32))
    parent_resource_id: Mapped[str | None] = mapped_column(String(32))
    ownership: Mapped[BindingOwnership] = mapped_column(
        Enum(BindingOwnership, native_enum=False, length=12)
    )
    state: Mapped[BindingState] = mapped_column(
        Enum(BindingState, native_enum=False, length=20)
    )
    desired_revision: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1")
    )
    applied_revision: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    deletion_intent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deletion_reason: Mapped[ResourceRemovalReason | None] = mapped_column(
        Enum(ResourceRemovalReason, native_enum=False, length=32)
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FarmTicketMetaCursor(Base):
    __tablename__ = "farm_ticket_v2_meta_cursors"

    guild_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_sequence: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0")
    )
    bootstrap_complete: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FarmTicketMetaReceipt(Base):
    __tablename__ = "farm_ticket_v2_meta_receipts"
    __table_args__ = (
        UniqueConstraint("guild_id", "event_id", name="uq_ftv2_meta_receipt_event"),
        UniqueConstraint("guild_id", "sequence", name="uq_ftv2_meta_receipt_sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    event_id: Mapped[str] = mapped_column(String(36))
    sequence: Mapped[int] = mapped_column(BigInteger)
    event_type: Mapped[str] = mapped_column(String(80))
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FarmTicketLegacyArchive(Base):
    __tablename__ = "farm_ticket_v2_legacy_archive"
    __table_args__ = (
        UniqueConstraint("source_namespace", "source_id", name="uq_ftv2_legacy_source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_namespace: Mapped[str] = mapped_column(String(80))
    source_id: Mapped[str] = mapped_column(String(120))
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict] = mapped_column(JsonType)
    checksum_sha256: Mapped[str] = mapped_column(String(64))
    archived_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FarmTicketFormDraft(Base):
    __tablename__ = "farm_ticket_v2_form_drafts"
    __table_args__ = (
        UniqueConstraint("ticket_id", "actor_id", name="uq_ftv2_form_draft_actor"),
        CheckConstraint("revision > 0", name="ck_ftv2_form_draft_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("farm_ticket_v2_tickets.id", ondelete="CASCADE"), index=True
    )
    guild_id: Mapped[str] = mapped_column(String(32), index=True)
    actor_id: Mapped[str] = mapped_column(String(32), index=True)
    operation_kind: Mapped[FormKind] = mapped_column(
        Enum(FormKind, native_enum=False, length=20)
    )
    target_entry_id: Mapped[str | None] = mapped_column(
        ForeignKey("farm_ticket_v2_entries.id", ondelete="RESTRICT")
    )
    step: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    values: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
