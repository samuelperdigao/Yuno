# ruff: noqa: E402

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import app.models  # noqa: E402,F401
from app.db import Base  # noqa: E402
from app.domain_modules.farm_tickets import proof_processing, services  # noqa: E402
from app.domain_modules.farm_tickets.domain import (  # noqa: E402
    BindingOwnership,
    BindingState,
    EntryRevisionStatus,
    FarmTicketConflict,
    FormKind,
    ObjectiveKind,
    OperationKind,
    OperationStatus,
    ProofNoLongerEligible,
    ProofStorageState,
    ResourceKind,
    ResourceRemovalReason,
    TicketCloseReason,
    TicketStatus,
    calculate_progress,
)
from app.domain_modules.farm_tickets.models import (  # noqa: E402
    FarmTicket,
    FarmTicketAllocation,
    FarmTicketCycle,
    FarmTicketDiscordBinding,
    FarmTicketEntry,
    FarmTicketEntryRevision,
    FarmTicketEvent,
    FarmTicketObjective,
    FarmTicketPendingOperation,
    FarmTicketProof,
)
from app.domain_modules.meta.contracts import (  # noqa: E402
    ActiveGoalForMember,
    GoalCycleSnapshot,
    GoalEvent,
    GoalObjectiveSnapshot,
)
from app.domain_modules.meta.domain import (
    ObjectiveKind as MetaObjectiveKind,  # noqa: E402
)
from app.domain_modules.registration.domain import (
    OrganizationMemberStatus,  # noqa: E402
)
from app.domain_modules.registration.identity import BaseMemberIdentity  # noqa: E402
from app.platform.models import AutomationTask, DeliveryOutbox  # noqa: E402
from app.platform.schemas import ActorContextIn  # noqa: E402


def _actor(user_id: str = "100") -> ActorContextIn:
    return ActorContextIn(
        guild_id="guild-a",
        user_id=user_id,
        correlation_id=f"test:{user_id}",
    )


async def _database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _ticket(
    session,
    *,
    targets: tuple[str, ...] = ("100",),
    guild_id: str = "guild-a",
    member_id: str = "100",
) -> FarmTicket:
    now = datetime.now(timezone.utc)
    ticket = FarmTicket(
        guild_id=guild_id,
        member_id=member_id,
        meta_goal_id=10,
        meta_cycle_id=20,
        registration_identity_id=f"identity-{guild_id}-{member_id}",
        member_name="Mineiro",
        player_id="6627",
        base_nickname="Mineiro | 6627",
        created_by="100",
    )
    session.add(ticket)
    await session.flush()
    session.add(
        FarmTicketCycle(
            ticket_id=ticket.id,
            guild_id=ticket.guild_id,
            meta_goal_id=ticket.meta_goal_id,
            meta_cycle_id=ticket.meta_cycle_id,
            goal_name="Meta semanal",
            timezone="America/Sao_Paulo",
            starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(days=1),
        )
    )
    for position, target in enumerate(targets):
        session.add(
            FarmTicketObjective(
                ticket_id=ticket.id,
                guild_id=ticket.guild_id,
                meta_objective_id=position + 1,
                kind=ObjectiveKind.ITEM,
                name=f"Item {position + 1}",
                unit="un",
                target_amount=Decimal(target),
                position=position,
            )
        )
    await session.commit()
    return ticket


async def _allow_cycle(*args, **kwargs) -> None:
    return None


async def _begin(
    session, ticket: FarmTicket, monkeypatch, *, amount: str = "50"
) -> dict:
    monkeypatch.setattr(services, "_assert_cycle_open", _allow_cycle)
    objective = await session.scalar(
        select(FarmTicketObjective).where(FarmTicketObjective.ticket_id == ticket.id)
    )
    await session.refresh(ticket)
    return await services.begin_operation(
        session,
        guild_id=ticket.guild_id,
        ticket_id=ticket.id,
        actor=_actor(),
        expected_version=ticket.revision,
        idempotency_key=f"begin:{ticket.id}:{ticket.revision}:{amount}",
        interaction_id=f"interaction:{ticket.id}:{ticket.revision}:{amount}",
        kind=OperationKind.CREATE_ENTRY,
        values=[(objective.id, Decimal(amount))],
    )


async def _confirm(
    session,
    ticket: FarmTicket,
    monkeypatch,
    *,
    amount: str = "50",
    message_id: str = "proof-message",
) -> dict:
    started = await _begin(session, ticket, monkeypatch, amount=amount)
    operation = await session.get(FarmTicketPendingOperation, started["id"])
    await session.refresh(ticket)
    claimed = await services.claim_proof(
        session,
        guild_id=ticket.guild_id,
        ticket_id=ticket.id,
        operation_id=operation.id,
        actor=_actor(),
        expected_version=ticket.revision,
        message_id=message_id,
        attachment_id=f"{message_id}-attachment",
        author_id="100",
        channel_id="600",
        received_at=operation.proof_deadline - timedelta(seconds=1),
        filename="proof.png",
        content_type="image/png",
        size_bytes=100,
        source_url="https://cdn.discord.test/proof.png",
    )
    return await services.confirm_proof(
        session,
        guild_id=ticket.guild_id,
        ticket_id=ticket.id,
        operation_id=operation.id,
        claim_token=claimed["claim_token"],
        object_key=f"{ticket.guild_id}/{ticket.meta_cycle_id}/{ticket.id}/{message_id}/proof",
        checksum_sha256=(message_id.encode().hex() + "0" * 64)[:64],
        size_bytes=100,
        content_type="image/png",
    )


def test_progress_caps_each_objective_but_preserves_real_excess() -> None:
    result = calculate_progress(
        [("a", Decimal("130"), Decimal("100")), ("b", Decimal("25"), Decimal("100"))]
    )
    assert result.objectives[0].launched == Decimal("130")
    assert result.objectives[0].percent == Decimal("130.00")
    assert result.percent == Decimal("62.50")


def test_multi_step_form_preserves_draft_and_starts_deadline_only_after_last_step(
    monkeypatch,
) -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                ticket = await _ticket(session, targets=("10",) * 7)
                monkeypatch.setattr(services, "_assert_cycle_open", _allow_cycle)
                opened = await services.open_form_draft(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    actor=_actor(),
                    expected_version=ticket.revision,
                    kind=FormKind.CREATE_ENTRY,
                    target_entry_id=None,
                )
                assert opened["total_steps"] == 2
                assert (
                    await session.scalar(
                        select(func.count(FarmTicketPendingOperation.id))
                    )
                    == 0
                )
                first = await services.save_form_step(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    draft_id=opened["id"],
                    actor=_actor(),
                    expected_version=ticket.revision,
                    draft_revision=opened["revision"],
                    step=0,
                    values=[
                        (item["objective_id"], Decimal("1"))
                        for item in opened["objectives"][:5]
                    ],
                    idempotency_key="multi-step-final",
                )
                assert first["completed"] is False
                assert first["draft"]["step"] == 1
                assert (
                    await session.scalar(
                        select(func.count(FarmTicketPendingOperation.id))
                    )
                    == 0
                )
                completed = await services.save_form_step(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    draft_id=opened["id"],
                    actor=_actor(),
                    expected_version=ticket.revision,
                    draft_revision=first["draft"]["revision"],
                    step=1,
                    values=[
                        (item["objective_id"], Decimal("0"))
                        for item in opened["objectives"][5:]
                    ],
                    idempotency_key="multi-step-final",
                )
                assert completed["completed"] is True
                operation = await session.get(
                    FarmTicketPendingOperation, completed["operation"]["id"]
                )
                assert operation.proof_deadline - operation.created_at == timedelta(
                    minutes=5
                )
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_administrative_actions_do_not_cancel_awaiting_proof(monkeypatch) -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                ticket = await _ticket(session)
                await _begin(session, ticket, monkeypatch)
                await session.refresh(ticket)
                for action, key in (
                    (services.approve_ticket, "approve"),
                    (services.finalize_ticket, "finalize"),
                ):
                    with pytest.raises(FarmTicketConflict, match="AWAITING_PROOF"):
                        await action(
                            session=session,
                            guild_id=ticket.guild_id,
                            ticket_id=ticket.id,
                            actor=_actor("900"),
                            expected_version=ticket.revision,
                            idempotency_key=key,
                        )
                with pytest.raises(FarmTicketConflict, match="nao sera cancelada"):
                    await services.delete_ticket(
                        session,
                        guild_id=ticket.guild_id,
                        ticket_id=ticket.id,
                        actor=_actor("900"),
                        expected_version=ticket.revision,
                        idempotency_key="delete",
                    )
                operation = await session.scalar(
                    select(FarmTicketPendingOperation).where(
                        FarmTicketPendingOperation.ticket_id == ticket.id
                    )
                )
                assert operation.status == OperationStatus.AWAITING_PROOF
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_proof_received_before_deadline_survives_processing_after_deadline(
    monkeypatch,
) -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                ticket = await _ticket(session)
                started = await _begin(session, ticket, monkeypatch)
                operation = await session.get(FarmTicketPendingOperation, started["id"])
                await session.refresh(ticket)
                received = operation.proof_deadline - timedelta(seconds=1)
                claimed = await services.claim_proof(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    operation_id=operation.id,
                    actor=_actor(),
                    expected_version=ticket.revision,
                    message_id="500",
                    attachment_id="501",
                    author_id="100",
                    channel_id="600",
                    received_at=received,
                    filename="proof.png",
                    content_type="image/png",
                    size_bytes=100,
                    source_url="https://cdn.discord.test/proof.png",
                )
                expired = await services.expire_operation(
                    session,
                    guild_id=ticket.guild_id,
                    operation_id=operation.id,
                    now=operation.proof_deadline + timedelta(hours=1),
                )
                assert expired is False
                await services.retry_proof(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    operation_id=operation.id,
                    claim_token=claimed["claim_token"],
                    error="S3 temporariamente indisponivel",
                )
                refreshed = await session.get(FarmTicketPendingOperation, operation.id)
                assert refreshed.status == OperationStatus.RETRYING_PROOF
                result = await services.confirm_proof(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    operation_id=operation.id,
                    claim_token=claimed["claim_token"],
                    object_key=f"guild-a/20/{ticket.id}/1/proof",
                    checksum_sha256="a" * 64,
                    size_bytes=100,
                    content_type="image/png",
                )
                assert result["launched"]
                assert result["status"] == TicketStatus.IN_PROGRESS.value
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_cycle_close_preserves_unwithdrawn_balance_without_synthetic_allocations(
    monkeypatch,
) -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                ticket = await _ticket(session, targets=("1000",))
                started = await _begin(session, ticket, monkeypatch, amount="1000")
                operation = await session.get(FarmTicketPendingOperation, started["id"])
                await session.refresh(ticket)
                claimed = await services.claim_proof(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    operation_id=operation.id,
                    actor=_actor(),
                    expected_version=ticket.revision,
                    message_id="510",
                    attachment_id="511",
                    author_id="100",
                    channel_id="600",
                    received_at=operation.proof_deadline - timedelta(seconds=1),
                    filename="proof.png",
                    content_type="image/png",
                    size_bytes=100,
                    source_url="https://cdn.discord.test/proof.png",
                )
                await services.confirm_proof(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    operation_id=operation.id,
                    claim_token=claimed["claim_token"],
                    object_key=f"guild-a/20/{ticket.id}/1/proof",
                    checksum_sha256="b" * 64,
                    size_bytes=100,
                    content_type="image/png",
                )
                await session.refresh(ticket)
                monkeypatch.setattr(services, "_assert_cycle_open", _allow_cycle)
                objective = await session.scalar(
                    select(FarmTicketObjective).where(
                        FarmTicketObjective.ticket_id == ticket.id
                    )
                )
                await services.withdraw(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    actor=_actor("900"),
                    expected_version=ticket.revision,
                    idempotency_key="withdraw-700",
                    values=[(objective.id, Decimal("700"))],
                )
                await session.refresh(ticket)
                closed = await services.freeze_and_close_for_cycle(
                    session,
                    ticket=ticket,
                    reason=TicketCloseReason.CYCLE_ENDED,
                    meta_event_id="event-end",
                    effective_at=datetime.now(timezone.utc),
                )
                await session.commit()
                assert closed is True
                await session.refresh(ticket)
                snapshot = ticket.frozen_totals[objective.id]
                assert snapshot == {
                    "name": objective.name,
                    "launched": "1000.000",
                    "withdrawn": "700.000",
                    "unwithdrawn": "300.000",
                }
                assert ticket.withdrawals_open is False
                assert (
                    int(
                        await session.scalar(
                            select(func.count(FarmTicketAllocation.id))
                        )
                        or 0
                    )
                    == 1
                )
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_manual_channel_delete_preserves_consolidated_result() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                ticket = await _ticket(session)
                ticket.status = TicketStatus.APPROVED
                ticket.result_finalized_at = datetime.now(timezone.utc)
                ticket.operations_closed_at = ticket.result_finalized_at
                ticket.withdrawals_open = False
                ticket.settlement_closed_at = ticket.result_finalized_at
                await session.commit()
                result = await services.delete_ticket(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    actor=_actor("900"),
                    expected_version=ticket.revision,
                    idempotency_key="delete-approved",
                )
                assert result["status"] == TicketStatus.APPROVED.value
                assert result["last_resource_removal_reason"] == "MANUAL_DELETE"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_streamed_image_is_stored_before_entry_confirmation(
    monkeypatch, tmp_path
) -> None:
    class Storage:
        def __init__(self) -> None:
            self.uploads = []

        async def put_file(self, **kwargs) -> None:
            self.uploads.append(kwargs)

        async def delete(self, **kwargs) -> None:
            return None

        async def presign_get(self, **kwargs) -> str:
            return "https://storage.test/proof"

        async def head(self, **kwargs) -> dict:
            return {}

    async def run() -> None:
        from PIL import Image

        engine, sessions = await _database()
        image_path = tmp_path / "proof.png"
        Image.new("RGB", (2, 2), color="red").save(image_path, format="PNG")

        async def downloaded(url: str):
            return image_path

        monkeypatch.setattr(proof_processing, "_download_to_temp", downloaded)
        try:
            async with sessions() as session:
                ticket = await _ticket(session)
                started = await _begin(session, ticket, monkeypatch)
                operation = await session.get(FarmTicketPendingOperation, started["id"])
                await session.refresh(ticket)
                claimed = await services.claim_proof(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    operation_id=operation.id,
                    actor=_actor(),
                    expected_version=ticket.revision,
                    message_id="storage-message",
                    attachment_id="storage-attachment",
                    author_id="100",
                    channel_id="600",
                    received_at=operation.proof_deadline - timedelta(seconds=1),
                    filename="proof.png",
                    content_type="application/octet-stream",
                    size_bytes=image_path.stat().st_size,
                    source_url="https://cdn.discord.test/proof",
                )
                storage = Storage()
                result = await proof_processing.process_claimed_proof(
                    session,
                    storage=storage,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    operation_id=operation.id,
                    claim_token=claimed["claim_token"],
                )
                assert storage.uploads[0]["content_type"] == "image/png"
                assert storage.uploads[0]["key"].startswith(f"guild-a/20/{ticket.id}/")
                assert result["launched"]
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_deeply_invalid_image_releases_claim_without_resetting_deadline(
    monkeypatch, tmp_path
) -> None:
    class Storage:
        async def put_file(self, **kwargs) -> None:
            raise AssertionError("Arquivo invalido nao pode chegar ao storage.")

    async def run() -> None:
        engine, sessions = await _database()
        invalid_path = tmp_path / "not-an-image.png"
        invalid_path.write_bytes(b"not an image")

        async def downloaded(url: str):
            return invalid_path

        monkeypatch.setattr(proof_processing, "_download_to_temp", downloaded)
        try:
            async with sessions() as session:
                ticket = await _ticket(session)
                started = await _begin(session, ticket, monkeypatch)
                operation = await session.get(FarmTicketPendingOperation, started["id"])
                original_deadline = operation.proof_deadline
                await session.refresh(ticket)
                claimed = await services.claim_proof(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    operation_id=operation.id,
                    actor=_actor(),
                    expected_version=ticket.revision,
                    message_id="invalid-message",
                    attachment_id="invalid-attachment",
                    author_id="100",
                    channel_id="600",
                    received_at=original_deadline - timedelta(seconds=1),
                    filename="proof.png",
                    content_type="image/png",
                    size_bytes=12,
                    source_url="https://cdn.discord.test/invalid",
                )
                result = await proof_processing.process_claimed_proof(
                    session,
                    storage=Storage(),
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    operation_id=operation.id,
                    claim_token=claimed["claim_token"],
                )
                refreshed = await session.get(FarmTicketPendingOperation, operation.id)
                assert result["status"] == OperationStatus.AWAITING_PROOF.value
                assert refreshed.proof_deadline == original_deadline
                assert refreshed.claim_token is None
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_open_ticket_uses_public_contract_snapshots_and_is_idempotent(
    monkeypatch,
) -> None:
    async def run() -> None:
        engine, sessions = await _database()
        now = datetime.now(timezone.utc)
        identity = BaseMemberIdentity(
            identity_id="identity-contract",
            guild_id="guild-a",
            discord_user_id="100",
            registered_name="Mineiro",
            player_id="6627",
            status=OrganizationMemberStatus.active,
            base_nickname="Mineiro | 6627",
            config_version=2,
            fingerprint="f" * 64,
        )
        goal = ActiveGoalForMember(
            goal_id=10,
            cycle=GoalCycleSnapshot(
                cycle_id=20,
                goal_id=10,
                guild_id="guild-a",
                name="Meta contrato",
                state="active",
                starts_at=now - timedelta(hours=1),
                ends_at=now + timedelta(days=1),
                timezone="America/Sao_Paulo",
                config_version_id=3,
            ),
            objectives=(
                GoalObjectiveSnapshot(
                    objective_id=30,
                    kind=MetaObjectiveKind.item,
                    name="Ferro",
                    unit="un",
                    item_quantity="100",
                    money_amount=None,
                    position=0,
                ),
            ),
        )

        async def identity_reader(*args, **kwargs):
            return identity

        async def goal_reader(*args, **kwargs):
            return goal

        monkeypatch.setattr(services, "read_base_member_identity", identity_reader)
        monkeypatch.setattr(
            services.meta_contracts, "get_active_goal_for_member", goal_reader
        )
        try:
            async with sessions() as session:
                opened = await services.open_ticket(
                    session,
                    guild_id="guild-a",
                    member_id="100",
                    actor=_actor(),
                    idempotency_key="open-contract",
                )
                duplicate = await services.open_ticket(
                    session,
                    guild_id="guild-a",
                    member_id="100",
                    actor=_actor("900"),
                    idempotency_key="open-admin",
                )
                assert duplicate["id"] == opened["id"]
                assert opened["member_name"] == "Mineiro"
                assert opened["player_id"] == "6627"
                assert opened["goal_name"] == "Meta contrato"
                assert opened["objectives"][0]["name"] == "Ferro"

                async def missing_identity(*args, **kwargs):
                    return None

                monkeypatch.setattr(
                    services, "read_base_member_identity", missing_identity
                )
                with pytest.raises(FarmTicketConflict, match="Registro ativo"):
                    await services.open_ticket(
                        session,
                        guild_id="guild-a",
                        member_id="200",
                        actor=_actor("200"),
                        idempotency_key="no-registration",
                    )
                monkeypatch.setattr(
                    services, "read_base_member_identity", identity_reader
                )

                async def missing_goal(*args, **kwargs):
                    return None

                monkeypatch.setattr(
                    services.meta_contracts, "get_active_goal_for_member", missing_goal
                )
                with pytest.raises(FarmTicketConflict, match="Meta ativa"):
                    await services.open_ticket(
                        session,
                        guild_id="guild-a",
                        member_id="201",
                        actor=_actor("201"),
                        idempotency_key="no-goal",
                    )
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_only_one_operation_and_only_author_can_claim_persisted_deadline(
    monkeypatch,
) -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                ticket = await _ticket(session)
                started = await _begin(session, ticket, monkeypatch)
                operation = await session.get(FarmTicketPendingOperation, started["id"])
                persisted_deadline = operation.proof_deadline
                await session.refresh(ticket)
                objective = await session.scalar(
                    select(FarmTicketObjective).where(
                        FarmTicketObjective.ticket_id == ticket.id
                    )
                )
                with pytest.raises(FarmTicketConflict, match="operacao AWAITING_PROOF"):
                    await services.begin_operation(
                        session,
                        guild_id=ticket.guild_id,
                        ticket_id=ticket.id,
                        actor=_actor("900"),
                        expected_version=ticket.revision,
                        idempotency_key="second-operation",
                        kind=OperationKind.CREATE_ENTRY,
                        values=[(objective.id, Decimal("1"))],
                    )
                with pytest.raises(FarmTicketConflict, match="autor"):
                    await services.claim_proof(
                        session,
                        guild_id=ticket.guild_id,
                        ticket_id=ticket.id,
                        operation_id=operation.id,
                        actor=_actor("900"),
                        expected_version=ticket.revision,
                        message_id="wrong-author",
                        attachment_id="wrong-author-attachment",
                        author_id="900",
                        channel_id="600",
                        received_at=persisted_deadline - timedelta(seconds=1),
                        filename="proof.png",
                        content_type="image/png",
                        size_bytes=100,
                        source_url="https://cdn.discord.test/proof.png",
                    )
                assert (
                    await session.get(FarmTicketPendingOperation, operation.id)
                ).proof_deadline == persisted_deadline
                assert await services.expire_operation(
                    session,
                    guild_id=ticket.guild_id,
                    operation_id=operation.id,
                    now=persisted_deadline + timedelta(seconds=1),
                )
                assert (await services.ticket_dict(session, ticket))["launched"][
                    objective.id
                ] == "0"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_edit_is_append_only_expires_to_original_and_allocation_blocks_it(
    monkeypatch,
) -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                ticket = await _ticket(session, targets=("100",))
                await _confirm(
                    session, ticket, monkeypatch, amount="80", message_id="edit-base"
                )
                await session.refresh(ticket)
                entry = await session.scalar(
                    select(FarmTicketEntry).where(
                        FarmTicketEntry.ticket_id == ticket.id
                    )
                )
                objective = await session.scalar(
                    select(FarmTicketObjective).where(
                        FarmTicketObjective.ticket_id == ticket.id
                    )
                )
                pending = await services.begin_operation(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    actor=_actor(),
                    expected_version=ticket.revision,
                    idempotency_key="edit-expire",
                    kind=OperationKind.EDIT_ENTRY,
                    target_entry_id=entry.id,
                    values=[(objective.id, Decimal("90"))],
                    now=datetime.now(timezone.utc) - timedelta(minutes=6),
                )
                await services.expire_operation(
                    session,
                    guild_id=ticket.guild_id,
                    operation_id=pending["id"],
                    now=datetime.now(timezone.utc),
                )
                revisions = list(
                    (
                        await session.execute(
                            select(FarmTicketEntryRevision)
                            .where(FarmTicketEntryRevision.entry_id == entry.id)
                            .order_by(FarmTicketEntryRevision.version)
                        )
                    ).scalars()
                )
                assert [item.status for item in revisions] == [
                    EntryRevisionStatus.CURRENT,
                    EntryRevisionStatus.REJECTED,
                ]
                await session.refresh(ticket)
                await services.withdraw(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    actor=_actor("900"),
                    expected_version=ticket.revision,
                    idempotency_key="edit-block-withdraw",
                    values=[(objective.id, Decimal("1"))],
                )
                await session.refresh(ticket)
                with pytest.raises(FarmTicketConflict, match="recolhimento"):
                    await services.begin_operation(
                        session,
                        guild_id=ticket.guild_id,
                        ticket_id=ticket.id,
                        actor=_actor(),
                        expected_version=ticket.revision,
                        idempotency_key="edit-after-allocation",
                        kind=OperationKind.EDIT_ENTRY,
                        target_entry_id=entry.id,
                        values=[(objective.id, Decimal("70"))],
                    )
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_fifo_multiple_partial_withdrawals_preserve_excess_and_progress(
    monkeypatch,
) -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                ticket = await _ticket(session, targets=("500",))
                await _confirm(
                    session, ticket, monkeypatch, amount="300", message_id="fifo-1"
                )
                await session.refresh(ticket)
                await _confirm(
                    session, ticket, monkeypatch, amount="400", message_id="fifo-2"
                )
                await session.refresh(ticket)
                objective = await session.scalar(
                    select(FarmTicketObjective).where(
                        FarmTicketObjective.ticket_id == ticket.id
                    )
                )
                result = await services.withdraw(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    actor=_actor("900"),
                    expected_version=ticket.revision,
                    idempotency_key="fifo-500",
                    values=[(objective.id, Decimal("500"))],
                )
                assert result["progress_percent"] == "100.00"
                assert result["launched"][objective.id] == "700.000"
                assert result["withdrawn"][objective.id] == "500.000"
                assert result["available"][objective.id] == "200.000"
                allocations = list(
                    (
                        await session.execute(
                            select(FarmTicketAllocation).order_by(
                                FarmTicketAllocation.created_at
                            )
                        )
                    ).scalars()
                )
                assert [Decimal(item.amount) for item in allocations] == [
                    Decimal("300.000"),
                    Decimal("200.000"),
                ]
                await session.refresh(ticket)
                with pytest.raises(FarmTicketConflict, match="saldo disponivel"):
                    await services.withdraw(
                        session,
                        guild_id=ticket.guild_id,
                        ticket_id=ticket.id,
                        actor=_actor("900"),
                        expected_version=ticket.revision,
                        idempotency_key="above-balance",
                        values=[(objective.id, Decimal("201"))],
                    )
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_assignment_replaces_owner_and_manual_results_keep_post_close_withdrawal(
    monkeypatch,
) -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                ticket = await _ticket(session, targets=("100",))
                await _confirm(
                    session,
                    ticket,
                    monkeypatch,
                    amount="50",
                    message_id="manual-result",
                )
                await session.refresh(ticket)
                first = await services.assign_ticket(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    actor=_actor("900"),
                    expected_version=ticket.revision,
                    idempotency_key="assign-900",
                    administrator_id="900",
                )
                second = await services.assign_ticket(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    actor=_actor("901"),
                    expected_version=first["revision"],
                    idempotency_key="assign-901",
                    administrator_id="901",
                )
                assert second["assigned_admin_id"] == "901"
                approved = await services.approve_ticket(
                    session=session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    actor=_actor("901"),
                    expected_version=second["revision"],
                    idempotency_key="approve-below-100",
                )
                assert approved["status"] == TicketStatus.APPROVED.value
                assert approved["withdrawals_open"] is True
                assert approved["allowed_actions"] == ["list_proofs", "withdraw"]
                objective = await session.scalar(
                    select(FarmTicketObjective).where(
                        FarmTicketObjective.ticket_id == ticket.id
                    )
                )
                withdrawn = await services.withdraw(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    actor=_actor("900"),
                    expected_version=approved["revision"],
                    idempotency_key="post-approve-withdraw",
                    values=[(objective.id, Decimal("50"))],
                )
                assert withdrawn["withdrawals_open"] is False
                assert withdrawn["allowed_actions"] == ["list_proofs"]
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_member_left_balance_policy_and_same_cycle_ticket_stays_non_operational(
    monkeypatch,
) -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                ticket = await _ticket(session, targets=("100",))
                await _confirm(
                    session, ticket, monkeypatch, amount="40", message_id="left-balance"
                )
                await session.refresh(ticket)
                event = services.meta_contracts.GoalEvent(
                    event_id="left-event",
                    sequence=1,
                    event_type=services.EVENT_PARTICIPANT_REMOVED,
                    event_version=1,
                    occurred_at=datetime.now(timezone.utc),
                    causation_id="left",
                    deduplication_key="left",
                    payload={
                        "member_id": "100",
                        "cycle_id": 20,
                        "reason": "left_guild",
                    },
                )
                assert await services._apply_meta_event(
                    session, guild_id="guild-a", event=event
                )
                await session.commit()
                view = await services.ticket_dict(session, ticket)
                assert view["member_left_at"] is not None
                assert view["operations_open"] is False
                assert view["withdrawals_open"] is True
                assert view["allowed_actions"] == ["list_proofs", "withdraw"]
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_external_and_planned_deletions_keep_historical_result(monkeypatch) -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                ticket = await _ticket(session)
                ticket.status = TicketStatus.APPROVED
                ticket.result_finalized_at = datetime.now(timezone.utc)
                ticket.operations_closed_at = ticket.result_finalized_at
                ticket.withdrawals_open = False
                session.add(
                    FarmTicketDiscordBinding(
                        ticket_id=ticket.id,
                        guild_id=ticket.guild_id,
                        kind=ResourceKind.TICKET_CHANNEL,
                        resource_id="700",
                        ownership=BindingOwnership.MANAGED,
                        state=BindingState.ACTIVE,
                    )
                )
                session.add(
                    FarmTicketDiscordBinding(
                        ticket_id=ticket.id,
                        guild_id=ticket.guild_id,
                        kind=ResourceKind.TICKET_THREAD,
                        resource_id="700",
                        parent_resource_id="700",
                        ownership=BindingOwnership.MANAGED,
                        state=BindingState.ACTIVE,
                    )
                )
                await session.commit()
                result = await services.record_external_resource_deletion(
                    session,
                    guild_id=ticket.guild_id,
                    resource_id="700",
                    observed_at=datetime.now(timezone.utc),
                )
                await session.refresh(ticket)
                assert result["action"] == "accept_removed"
                assert ticket.status == TicketStatus.APPROVED
                assert (
                    ticket.last_resource_removal_reason
                    == ResourceRemovalReason.MANUAL_DELETE
                )
                same_snowflake = (
                    (
                        await session.execute(
                            select(FarmTicketDiscordBinding).where(
                                FarmTicketDiscordBinding.resource_id == "700"
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(same_snowflake) == 2
                assert all(
                    item.state == BindingState.DELETED for item in same_snowflake
                )

                binding = await session.scalar(
                    select(FarmTicketDiscordBinding).where(
                        FarmTicketDiscordBinding.resource_id == "700"
                    )
                )
                binding.state = BindingState.DELETE_PENDING
                binding.deletion_intent_at = datetime.now(timezone.utc)
                binding.deletion_reason = ResourceRemovalReason.CYCLE_CLEANUP
                await session.commit()
                planned = await services.record_external_resource_deletion(
                    session,
                    guild_id=ticket.guild_id,
                    resource_id="700",
                    observed_at=datetime.now(timezone.utc),
                )
                assert planned["action"] == "planned_delete"
                assert ticket.status == TicketStatus.APPROVED
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_storage_cleanup_retains_until_thread_copy_then_retries(monkeypatch) -> None:
    class Storage:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        async def delete(self, *, key: str) -> None:
            self.deleted.append(key)

    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                ticket = await _ticket(session)
                await _confirm(
                    session,
                    ticket,
                    monkeypatch,
                    amount="10",
                    message_id="cleanup-proof",
                )
                ticket.binding_released_at = datetime.now(timezone.utc)
                await session.commit()
                storage = Storage()
                retained = await proof_processing.cleanup_released_ticket_proofs(
                    session,
                    storage=storage,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                )
                assert retained == {"deleted": 0, "retained": 1}
                proof = await session.scalar(
                    select(FarmTicketProof).where(
                        FarmTicketProof.ticket_id == ticket.id
                    )
                )
                assert proof.storage_state == ProofStorageState.RETAINED
                await services.mark_proof_thread_delivered(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    proof_id=proof.id,
                    external_message_id="999",
                )
                deleted = await proof_processing.cleanup_released_ticket_proofs(
                    session,
                    storage=storage,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                )
                assert deleted == {"deleted": 1, "retained": 0}
                assert storage.deleted == [proof.object_key]
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_cycle_event_waits_for_timely_claim_then_confirms_before_closing(
    monkeypatch,
) -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                ticket = await _ticket(session)
                started = await _begin(session, ticket, monkeypatch)
                operation = await session.get(FarmTicketPendingOperation, started["id"])
                effective_at = operation.proof_deadline - timedelta(milliseconds=500)
                received_at = effective_at - timedelta(milliseconds=500)
                await session.refresh(ticket)
                claimed = await services.claim_proof(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    operation_id=operation.id,
                    actor=_actor(),
                    expected_version=ticket.revision,
                    message_id="cycle-timely",
                    attachment_id="cycle-timely-attachment",
                    author_id="100",
                    channel_id="600",
                    received_at=received_at,
                    filename="proof.png",
                    content_type="image/png",
                    size_bytes=100,
                    source_url="https://cdn.discord.test/proof.png",
                )
                event = GoalEvent(
                    event_id="cycle-end-timely",
                    sequence=1,
                    event_type=services.EVENT_CYCLE_ENDED,
                    event_version=1,
                    occurred_at=effective_at,
                    causation_id="cycle-end-timely",
                    deduplication_key="cycle-end-timely",
                    payload={"cycle_id": ticket.meta_cycle_id, "reason": "completed"},
                )
                assert not await services._apply_meta_event(
                    session, guild_id=ticket.guild_id, event=event
                )
                await session.commit()
                result = await services.confirm_proof(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    operation_id=operation.id,
                    claim_token=claimed["claim_token"],
                    object_key=f"guild-a/20/{ticket.id}/cycle-timely/proof",
                    checksum_sha256="d" * 64,
                    size_bytes=100,
                    content_type="image/png",
                )
                assert next(iter(result["launched"].values())) == "50.000"
                assert await services._apply_meta_event(
                    session, guild_id=ticket.guild_id, event=event
                )
                await session.commit()
                await session.refresh(ticket)
                assert ticket.status == TicketStatus.FINALIZED_INCOMPLETE
                assert ticket.binding_released_at == effective_at
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_cycle_event_rejects_claim_received_after_effective_end(monkeypatch) -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                ticket = await _ticket(session)
                started = await _begin(session, ticket, monkeypatch)
                operation = await session.get(FarmTicketPendingOperation, started["id"])
                effective_at = operation.proof_deadline - timedelta(seconds=2)
                received_at = effective_at + timedelta(seconds=1)
                await session.refresh(ticket)
                claimed = await services.claim_proof(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    operation_id=operation.id,
                    actor=_actor(),
                    expected_version=ticket.revision,
                    message_id="cycle-late",
                    attachment_id="cycle-late-attachment",
                    author_id="100",
                    channel_id="600",
                    received_at=received_at,
                    filename="proof.png",
                    content_type="image/png",
                    size_bytes=100,
                    source_url="https://cdn.discord.test/proof.png",
                )
                event = GoalEvent(
                    event_id="cycle-end-late",
                    sequence=1,
                    event_type=services.EVENT_CYCLE_ENDED,
                    event_version=1,
                    occurred_at=effective_at,
                    causation_id="cycle-end-late",
                    deduplication_key="cycle-end-late",
                    payload={"cycle_id": ticket.meta_cycle_id, "reason": "completed"},
                )
                assert not await services._apply_meta_event(
                    session, guild_id=ticket.guild_id, event=event
                )
                await session.commit()
                with pytest.raises(ProofNoLongerEligible):
                    await services.confirm_proof(
                        session,
                        guild_id=ticket.guild_id,
                        ticket_id=ticket.id,
                        operation_id=operation.id,
                        claim_token=claimed["claim_token"],
                        object_key=f"guild-a/20/{ticket.id}/cycle-late/proof",
                        checksum_sha256="e" * 64,
                        size_bytes=100,
                        content_type="image/png",
                    )
                rejected = await services.reject_invalid_proof(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    operation_id=operation.id,
                    claim_token=claimed["claim_token"],
                    reason="Recebido depois do encerramento efetivo.",
                    now=operation.proof_deadline + timedelta(microseconds=1),
                )
                assert rejected["status"] == OperationStatus.EXPIRED.value
                assert await services._apply_meta_event(
                    session, guild_id=ticket.guild_id, event=event
                )
                await session.commit()
                view = await services.ticket_dict(session, ticket)
                assert all(Decimal(value) == 0 for value in view["launched"].values())
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_tenth_infrastructure_failure_becomes_recorded_recoverable_failure(
    monkeypatch,
) -> None:
    class Storage:
        async def put_file(self, **kwargs) -> None:
            raise AssertionError("download falha antes do upload")

    async def unavailable(url: str):
        raise RuntimeError("CDN temporariamente indisponivel")

    async def run() -> None:
        engine, sessions = await _database()
        monkeypatch.setattr(proof_processing, "_download_to_temp", unavailable)
        try:
            async with sessions() as session:
                ticket = await _ticket(session)
                started = await _begin(session, ticket, monkeypatch)
                operation = await session.get(FarmTicketPendingOperation, started["id"])
                await session.refresh(ticket)
                claimed = await services.claim_proof(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    operation_id=operation.id,
                    actor=_actor(),
                    expected_version=ticket.revision,
                    message_id="infra-final",
                    attachment_id="infra-final-attachment",
                    author_id="100",
                    channel_id="600",
                    received_at=operation.proof_deadline - timedelta(seconds=1),
                    filename="proof.png",
                    content_type="image/png",
                    size_bytes=100,
                    source_url="https://cdn.discord.test/proof.png",
                )
                operation.attempts = proof_processing.MAX_PROOF_PROCESSING_ATTEMPTS - 1
                await session.commit()
                with pytest.raises(RuntimeError, match="CDN"):
                    await proof_processing.process_claimed_proof(
                        session,
                        storage=Storage(),
                        guild_id=ticket.guild_id,
                        ticket_id=ticket.id,
                        operation_id=operation.id,
                        claim_token=claimed["claim_token"],
                    )
                await session.refresh(operation)
                assert operation.status == OperationStatus.FAILED
                assert operation.failed_recoverably is True
                await session.refresh(ticket)
                approved = await services.approve_ticket(
                    session=session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    actor=_actor("900"),
                    expected_version=ticket.revision,
                    idempotency_key="approve-after-definitive-failure",
                )
                assert approved["status"] == TicketStatus.APPROVED.value
                assert all(
                    Decimal(value) == 0 for value in approved["launched"].values()
                )
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_thread_recovery_reconstructs_all_events_once_in_sequence() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                ticket = await _ticket(session)
                for sequence in range(1, 4):
                    await services._event(
                        session,
                        ticket=ticket,
                        event_type=f"acceptance.event.{sequence}",
                        actor_id="Yuno",
                        deduplication_key=f"acceptance-event-{sequence}",
                        payload={"sequence": sequence},
                    )
                await session.commit()
                await services.upsert_discord_binding(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    kind=ResourceKind.TICKET_THREAD.value,
                    resource_id="thread-600",
                    parent_resource_id="log-500",
                    ownership=BindingOwnership.MANAGED.value,
                    idempotency_key="thread-first",
                )
                await services.upsert_discord_binding(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    kind=ResourceKind.TICKET_THREAD.value,
                    resource_id="thread-600",
                    parent_resource_id="log-500",
                    ownership=BindingOwnership.MANAGED.value,
                    idempotency_key="thread-recovery",
                )
                deliveries = list(
                    (
                        await session.execute(
                            select(DeliveryOutbox)
                            .where(
                                DeliveryOutbox.guild_id == ticket.guild_id,
                                DeliveryOutbox.module_key == "farm_tickets",
                                DeliveryOutbox.renderer_key == "farm_tickets.event",
                                DeliveryOutbox.resource_id.in_(
                                    select(FarmTicketEvent.id).where(
                                        FarmTicketEvent.ticket_id == ticket.id
                                    )
                                ),
                            )
                            .order_by(DeliveryOutbox.priority)
                        )
                    ).scalars()
                )
                assert [item.payload["sequence"] for item in deliveries] == [1, 2, 3]
                assert len({item.idempotency_key for item in deliveries}) == 3
                assert all(item.destination_id == "thread-600" for item in deliveries)
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_multi_item_and_money_entry_and_withdrawal_keep_numeric_precision(
    monkeypatch,
) -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                ticket = await _ticket(session, targets=("100", "1000"))
                objectives = list(
                    (
                        await session.execute(
                            select(FarmTicketObjective)
                            .where(FarmTicketObjective.ticket_id == ticket.id)
                            .order_by(FarmTicketObjective.position)
                        )
                    ).scalars()
                )
                objectives[1].kind = ObjectiveKind.MONEY
                objectives[1].name = "Dinheiro"
                objectives[1].unit = "R$"
                await session.commit()
                monkeypatch.setattr(services, "_assert_cycle_open", _allow_cycle)
                operation = await services.begin_operation(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    actor=_actor(),
                    expected_version=ticket.revision,
                    idempotency_key="mixed-entry",
                    kind=OperationKind.CREATE_ENTRY,
                    values=[
                        (objectives[0].id, Decimal("25.1234")),
                        (objectives[1].id, Decimal("125.127")),
                    ],
                )
                row = await session.get(FarmTicketPendingOperation, operation["id"])
                await session.refresh(ticket)
                claimed = await services.claim_proof(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    operation_id=row.id,
                    actor=_actor(),
                    expected_version=ticket.revision,
                    message_id="mixed-proof",
                    attachment_id="mixed-proof-attachment",
                    author_id="100",
                    channel_id="600",
                    received_at=row.proof_deadline - timedelta(seconds=1),
                    filename="proof.png",
                    content_type="image/png",
                    size_bytes=100,
                    source_url="https://cdn.discord.test/proof.png",
                )
                confirmed = await services.confirm_proof(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    operation_id=row.id,
                    claim_token=claimed["claim_token"],
                    object_key=f"guild-a/20/{ticket.id}/mixed/proof",
                    checksum_sha256="f" * 64,
                    size_bytes=100,
                    content_type="image/png",
                )
                assert confirmed["launched"][objectives[0].id] == "25.123"
                assert confirmed["launched"][objectives[1].id] == "125.130"
                withdrawn = await services.withdraw(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    actor=_actor("900"),
                    expected_version=confirmed["revision"],
                    idempotency_key="mixed-withdrawal",
                    values=[
                        (objectives[0].id, Decimal("5.123")),
                        (objectives[1].id, Decimal("25.126")),
                    ],
                )
                assert withdrawn["withdrawn"][objectives[0].id] == "5.123"
                assert withdrawn["withdrawn"][objectives[1].id] == "25.130"
                assert (
                    int(
                        await session.scalar(
                            select(func.count(FarmTicketAllocation.id)).where(
                                FarmTicketAllocation.ticket_id == ticket.id
                            )
                        )
                        or 0
                    )
                    == 2
                )
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_timeout_deadline_and_job_survive_session_restart(monkeypatch) -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as first_session:
                ticket = await _ticket(first_session, member_id="restart-member")
                started = await _begin(first_session, ticket, monkeypatch)
                operation = await first_session.get(
                    FarmTicketPendingOperation, started["id"]
                )
                operation_id = operation.id
                deadline = operation.proof_deadline
                assert (
                    int(
                        await first_session.scalar(
                            select(func.count(AutomationTask.id)).where(
                                AutomationTask.module_key == "farm_tickets",
                                AutomationTask.job_key
                                == "farm_tickets.operation.expire",
                                AutomationTask.resource_id == operation_id,
                            )
                        )
                        or 0
                    )
                    == 1
                )
            # Nova sessao representa o processo recuperando o job apos restart.
            async with sessions() as recovered_session:
                assert await services.expire_operation(
                    recovered_session,
                    guild_id="guild-a",
                    operation_id=operation_id,
                    now=deadline + timedelta(seconds=1),
                )
                recovered = await recovered_session.get(
                    FarmTicketPendingOperation, operation_id
                )
                assert recovered.status == OperationStatus.EXPIRED
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_valid_edit_requires_new_proof_and_can_auto_approve(monkeypatch) -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                ticket = await _ticket(session, targets=("100",))
                await _confirm(
                    session,
                    ticket,
                    monkeypatch,
                    amount="50",
                    message_id="edit-auto-base",
                )
                await session.refresh(ticket)
                entry = await session.scalar(
                    select(FarmTicketEntry).where(
                        FarmTicketEntry.ticket_id == ticket.id
                    )
                )
                objective = await session.scalar(
                    select(FarmTicketObjective).where(
                        FarmTicketObjective.ticket_id == ticket.id
                    )
                )
                operation = await services.begin_operation(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    actor=_actor(),
                    expected_version=ticket.revision,
                    idempotency_key="edit-auto",
                    kind=OperationKind.EDIT_ENTRY,
                    target_entry_id=entry.id,
                    values=[(objective.id, Decimal("100"))],
                )
                row = await session.get(FarmTicketPendingOperation, operation["id"])
                assert row.status == OperationStatus.AWAITING_PROOF
                await session.refresh(ticket)
                claimed = await services.claim_proof(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    operation_id=row.id,
                    actor=_actor(),
                    expected_version=ticket.revision,
                    message_id="edit-auto-proof",
                    attachment_id="edit-auto-proof-attachment",
                    author_id="100",
                    channel_id="600",
                    received_at=row.proof_deadline - timedelta(seconds=1),
                    filename="proof.png",
                    content_type="image/png",
                    size_bytes=100,
                    source_url="https://cdn.discord.test/proof.png",
                )
                edited = await services.confirm_proof(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    operation_id=row.id,
                    claim_token=claimed["claim_token"],
                    object_key=f"guild-a/20/{ticket.id}/edit/proof",
                    checksum_sha256="1" * 64,
                    size_bytes=100,
                    content_type="image/png",
                )
                assert edited["status"] == TicketStatus.APPROVED.value
                assert edited["progress_percent"] == "100.00"
                revisions = list(
                    (
                        await session.execute(
                            select(FarmTicketEntryRevision)
                            .where(FarmTicketEntryRevision.entry_id == entry.id)
                            .order_by(FarmTicketEntryRevision.version)
                        )
                    ).scalars()
                )
                assert [item.status for item in revisions] == [
                    EntryRevisionStatus.SUPERSEDED,
                    EntryRevisionStatus.CURRENT,
                ]
                assert (
                    int(
                        await session.scalar(
                            select(func.count(FarmTicketProof.id)).where(
                                FarmTicketProof.ticket_id == ticket.id
                            )
                        )
                        or 0
                    )
                    == 2
                )
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_incomplete_finalization_keeps_withdrawal_then_new_goal_freezes_balance(
    monkeypatch,
) -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                ticket = await _ticket(session, targets=("100",))
                await _confirm(
                    session, ticket, monkeypatch, amount="80", message_id="incomplete"
                )
                await session.refresh(ticket)
                finalized = await services.finalize_ticket(
                    session=session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    actor=_actor("900"),
                    expected_version=ticket.revision,
                    idempotency_key="final-incomplete",
                )
                assert finalized["status"] == TicketStatus.FINALIZED_INCOMPLETE.value
                assert finalized["allowed_actions"] == ["list_proofs", "withdraw"]
                objective = await session.scalar(
                    select(FarmTicketObjective).where(
                        FarmTicketObjective.ticket_id == ticket.id
                    )
                )
                partially = await services.withdraw(
                    session,
                    guild_id=ticket.guild_id,
                    ticket_id=ticket.id,
                    actor=_actor("900"),
                    expected_version=finalized["revision"],
                    idempotency_key="incomplete-withdraw-30",
                    values=[(objective.id, Decimal("30"))],
                )
                await session.refresh(ticket)
                assert partially["available"][objective.id] == "50.000"
                assert await services.freeze_and_close_for_cycle(
                    session,
                    ticket=ticket,
                    reason=TicketCloseReason.NEW_GOAL,
                    meta_event_id="new-goal-incomplete",
                    effective_at=datetime.now(timezone.utc),
                )
                await session.commit()
                await session.refresh(ticket)
                assert ticket.status == TicketStatus.FINALIZED_INCOMPLETE
                assert ticket.close_reason == TicketCloseReason.NEW_GOAL
                assert ticket.frozen_launched_total == Decimal("80.000")
                assert ticket.frozen_withdrawn_total == Decimal("30.000")
                assert ticket.frozen_unwithdrawn_total == Decimal("50.000")
                assert ticket.withdrawals_open is False
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_manual_delete_rules_member_leave_without_balance_and_multi_guild_isolation(
    monkeypatch,
) -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                empty = await _ticket(session)
                closed = await services.delete_ticket(
                    session,
                    guild_id=empty.guild_id,
                    ticket_id=empty.id,
                    actor=_actor("900"),
                    expected_version=empty.revision,
                    idempotency_key="delete-empty-operational",
                )
                assert closed["status"] == TicketStatus.CLOSED_MANUALLY.value

                ticket = await _ticket(session, targets=("100",), member_id="200")
                await _confirm(
                    session,
                    ticket,
                    monkeypatch,
                    amount="20",
                    message_id="delete-balance",
                )
                await session.refresh(ticket)
                with pytest.raises(FarmTicketConflict, match="saldo"):
                    await services.delete_ticket(
                        session,
                        guild_id=ticket.guild_id,
                        ticket_id=ticket.id,
                        actor=_actor("900"),
                        expected_version=ticket.revision,
                        idempotency_key="delete-with-balance",
                    )

                no_balance = await _ticket(session, member_id="300")
                left = GoalEvent(
                    event_id="left-no-balance",
                    sequence=1,
                    event_type=services.EVENT_PARTICIPANT_REMOVED,
                    event_version=1,
                    occurred_at=datetime.now(timezone.utc),
                    causation_id="left-no-balance",
                    deduplication_key="left-no-balance",
                    payload={
                        "member_id": "300",
                        "cycle_id": 20,
                        "reason": "left_guild",
                    },
                )
                assert await services._apply_meta_event(
                    session, guild_id="guild-a", event=left
                )
                await session.commit()
                await session.refresh(no_balance)
                assert no_balance.binding_released_at is not None
                assert no_balance.withdrawals_open is False
                identity = BaseMemberIdentity(
                    identity_id="identity-guild-a-300",
                    guild_id="guild-a",
                    discord_user_id="300",
                    registered_name="Mineiro",
                    player_id="6627",
                    status=OrganizationMemberStatus.active,
                    base_nickname="Mineiro | 6627",
                    config_version=2,
                    fingerprint="f" * 64,
                )
                active_goal = ActiveGoalForMember(
                    goal_id=10,
                    cycle=GoalCycleSnapshot(
                        cycle_id=20,
                        goal_id=10,
                        guild_id="guild-a",
                        name="Meta semanal",
                        state="active",
                        starts_at=datetime.now(timezone.utc) - timedelta(hours=1),
                        ends_at=datetime.now(timezone.utc) + timedelta(days=1),
                        timezone="America/Sao_Paulo",
                        config_version_id=2,
                    ),
                    objectives=(
                        GoalObjectiveSnapshot(
                            objective_id=1,
                            kind=MetaObjectiveKind.item,
                            name="Item 1",
                            unit="un",
                            item_quantity="100",
                            money_amount=None,
                            position=0,
                        ),
                    ),
                )

                async def returned_identity(*args, **kwargs):
                    return identity

                async def returned_goal(*args, **kwargs):
                    return active_goal

                monkeypatch.setattr(
                    services, "read_base_member_identity", returned_identity
                )
                monkeypatch.setattr(
                    services.meta_contracts,
                    "get_active_goal_for_member",
                    returned_goal,
                )
                with pytest.raises(FarmTicketConflict, match="nao sera reativada"):
                    await services.open_ticket(
                        session,
                        guild_id="guild-a",
                        member_id="300",
                        actor=_actor("300"),
                        idempotency_key="return-same-cycle",
                    )

                other = await _ticket(session, guild_id="guild-b", member_id="400")
                guild_a = await services.list_tickets(
                    session, guild_id="guild-a", active_only=False
                )
                guild_b = await services.list_tickets(
                    session, guild_id="guild-b", active_only=False
                )
                assert all(item["guild_id"] == "guild-a" for item in guild_a)
                assert [item["id"] for item in guild_b] == [other.id]
        finally:
            await engine.dispose()

    asyncio.run(run())
