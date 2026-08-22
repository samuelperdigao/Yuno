import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import app.models  # noqa: E402,F401
from app.db import Base  # noqa: E402
from app.domain_modules.registration import services  # noqa: E402
from app.domain_modules.registration.domain import (  # noqa: E402
    OrganizationMemberStatus,
    RegistrationRequestStatus,
)
from app.domain_modules.registration.models import OrganizationMember  # noqa: E402
from app.domain_modules.registration.schemas import (  # noqa: E402
    RegistrationConfig,
    RegistrationSubmit,
)
from app.platform.models import (  # noqa: E402
    AuditEntry,
    DeliveryOutbox,
    ModuleConfigVersion,
    ModuleInstance,
    ModuleLifecycle,
    RuntimeMode,
)


async def _database():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    return engine, sessions


async def _configure(session, guild_id: str = "100") -> None:
    config = RegistrationConfig(
        panel_channel_id="1001",
        approval_channel_id="1002",
        log_channel_id="1003",
        member_role_id="1004",
        approver_role_ids=["1005"],
    ).model_dump(mode="json")
    instance = ModuleInstance(
        guild_id=guild_id,
        module_key="registration",
        lifecycle=ModuleLifecycle.active,
        runtime_mode=RuntimeMode.domain,
        contract_version=1,
        domain_version="2.0.0",
    )
    session.add(instance)
    await session.flush()
    version = ModuleConfigVersion(
        module_instance_id=instance.id,
        guild_id=guild_id,
        module_key="registration",
        version=1,
        schema_version=1,
        data=config,
        content_hash="a" * 64,
        published_by="900",
    )
    session.add(version)
    await session.flush()
    instance.published_config_version_id = version.id
    await session.commit()


def test_registration_service_approval_idempotency_outbox_and_reactivation() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                await _configure(session)
                request = await services.submit_request(
                    session,
                    guild_id="100",
                    actor_id="10",
                    correlation_id="submit-1",
                    data=RegistrationSubmit(name="  Ana   Silva ", player_id="００1"),
                    panel_config_version=1,
                )
                assert request.player_id_original == "001"
                assert request.player_id_normalized == "001"
                assert request.submitted_name == "Ana Silva"

                claimed, config = await services.claim_approval(
                    session,
                    guild_id="100",
                    request_id=request.id,
                    actor_id="20",
                    correlation_id="approve-1",
                )
                token = claimed.processing_token
                assert token and claimed.status == RegistrationRequestStatus.processing
                await services.record_preflight(
                    session,
                    guild_id="100",
                    request_id=request.id,
                    actor_id="20",
                    operation_token=token,
                    previous_nickname="Antes",
                    role_was_present=False,
                    target_nickname="Ana Silva | 001",
                    correlation_id="approve-1",
                )
                await services.record_discord_step(
                    session,
                    guild_id="100",
                    request_id=request.id,
                    actor_id="20",
                    operation_token=token,
                    step="nickname",
                    correlation_id="approve-1",
                )
                await services.record_discord_step(
                    session,
                    guild_id="100",
                    request_id=request.id,
                    actor_id="20",
                    operation_token=token,
                    step="role",
                    correlation_id="approve-1",
                )
                approved, member = await services.complete_approval(
                    session,
                    guild_id="100",
                    request_id=request.id,
                    actor_id="20",
                    correlation_id="approve-1",
                    operation_token=token,
                )
                assert approved.status == RegistrationRequestStatus.approved
                assert member.status == OrganizationMemberStatus.active
                same_request, same_member = await services.complete_approval(
                    session,
                    guild_id="100",
                    request_id=request.id,
                    actor_id="20",
                    correlation_id="approve-retry",
                    operation_token=token,
                )
                assert same_request.id == request.id and same_member.id == member.id

                actions = set(
                    (
                        await session.execute(
                            select(AuditEntry.action).where(AuditEntry.guild_id == "100")
                        )
                    ).scalars()
                )
                assert {
                    "registration.request_submitted",
                    "registration.request_approved",
                } <= actions
                deliveries = list(
                    (
                        await session.execute(
                            select(DeliveryOutbox).where(DeliveryOutbox.guild_id == "100")
                        )
                    ).scalars()
                )
                assert {item.renderer_key for item in deliveries} == {
                    "registration.review_request",
                    "registration.review_update",
                    "registration.log_approved",
                    "registration.member_approved",
                }
                approved_log = next(
                    item
                    for item in deliveries
                    if item.renderer_key == "registration.log_approved"
                )
                assert approved_log.payload == {
                    "schema_version": 2,
                    "request_id": request.id,
                    "decision": "approved",
                    "discord_user_id": "10",
                    "submitted_name": "Ana Silva",
                    "player_id": "001",
                    "reviewed_by": "20",
                    "decision_at": f"{approved.approved_at.isoformat()}Z",
                    "reason": None,
                    "previous_nickname": "Antes",
                    "target_nickname": "Ana Silva | 001",
                    "member_role_id": "1004",
                    "role_was_present": False,
                    "nickname_applied": True,
                    "role_applied": True,
                    "config_version": 1,
                    "log_approved_title": "Registro aprovado",
                    "log_rejected_title": "Registro rejeitado",
                    "log_footer": "Yuno • Sistema de Registro",
                    "show_member_avatar": True,
                    "approved_dm_title": "Registro aprovado",
                    "rejected_dm_title": "Registro não aprovado",
                }

                await services.deactivate_member(
                    session,
                    guild_id="100",
                    discord_user_id="10",
                    actor_id=None,
                    correlation_id="leave-1",
                )
                inactive = await session.scalar(
                    select(OrganizationMember).where(OrganizationMember.id == member.id)
                )
                assert inactive.status == OrganizationMemberStatus.inactive
                second = await services.submit_request(
                    session,
                    guild_id="100",
                    actor_id="10",
                    correlation_id="submit-2",
                    data=RegistrationSubmit(name="Ana Silva", player_id="001"),
                )
                second_claim, _ = await services.claim_approval(
                    session,
                    guild_id="100",
                    request_id=second.id,
                    actor_id="20",
                    correlation_id="approve-2",
                )
                token2 = second_claim.processing_token
                await services.record_preflight(
                    session,
                    guild_id="100",
                    request_id=second.id,
                    actor_id="20",
                    operation_token=token2,
                    previous_nickname=None,
                    role_was_present=True,
                    target_nickname="Ana Silva | 001",
                    correlation_id="approve-2",
                )
                for step in ("nickname", "role"):
                    await services.record_discord_step(
                        session,
                        guild_id="100",
                        request_id=second.id,
                        actor_id="20",
                        operation_token=token2,
                        step=step,
                        correlation_id="approve-2",
                    )
                _, reactivated = await services.complete_approval(
                    session,
                    guild_id="100",
                    request_id=second.id,
                    actor_id="20",
                    correlation_id="approve-2",
                    operation_token=token2,
                )
                assert reactivated.id == member.id
                assert reactivated.status == OrganizationMemberStatus.active
                assert config.member_role_id == "1004"
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_registration_compensation_release_rejection_and_tenant_isolation() -> None:
    async def run() -> None:
        engine, sessions = await _database()
        try:
            async with sessions() as session:
                await _configure(session, "100")
                await _configure(session, "200")
                request = await services.submit_request(
                    session,
                    guild_id="100",
                    actor_id="11",
                    correlation_id="submit",
                    data=RegistrationSubmit(name="Bia", player_id="002"),
                )
                with pytest.raises(HTTPException) as cross:
                    await services.get_request(
                        session, guild_id="200", request_id=request.id
                    )
                assert cross.value.status_code == 404
                claimed, _ = await services.claim_approval(
                    session,
                    guild_id="100",
                    request_id=request.id,
                    actor_id="21",
                    correlation_id="claim",
                )
                with pytest.raises(HTTPException) as competing:
                    await services.claim_approval(
                        session,
                        guild_id="100",
                        request_id=request.id,
                        actor_id="22",
                        correlation_id="claim-2",
                    )
                assert competing.value.status_code == 409
                released = await services.fail_approval(
                    session,
                    guild_id="100",
                    request_id=request.id,
                    actor_id="21",
                    correlation_id="failure",
                    operation_token=claimed.processing_token,
                    compensated=True,
                    error_code="discord_forbidden",
                )
                assert released.status == RegistrationRequestStatus.pending
                rejected = await services.reject_request(
                    session,
                    guild_id="100",
                    request_id=request.id,
                    actor_id="21",
                    correlation_id="reject",
                    reason="Dados divergentes",
                )
                assert rejected.status == RegistrationRequestStatus.rejected
                assert rejected.rejection_reason == "Dados divergentes"
                rejected_log = await session.scalar(
                    select(DeliveryOutbox).where(
                        DeliveryOutbox.guild_id == "100",
                        DeliveryOutbox.renderer_key == "registration.log_rejected",
                    )
                )
                assert rejected_log is not None
                assert rejected_log.payload["decision"] == "rejected"
                assert rejected_log.payload["discord_user_id"] == "11"
                assert rejected_log.payload["reviewed_by"] == "21"
                assert rejected_log.payload["submitted_name"] == "Bia"
                assert rejected_log.payload["player_id"] == "002"
                assert rejected_log.payload["reason"] == "Dados divergentes"
                assert rejected_log.payload["member_role_id"] == "1004"
                assert rejected_log.payload["target_nickname"] is None
                assert rejected_log.payload["decision_at"] == f"{rejected.rejected_at.isoformat()}Z"
                with pytest.raises(HTTPException):
                    await services.reject_request(
                        session,
                        guild_id="100",
                        request_id=request.id,
                        actor_id="21",
                        correlation_id="reject-again",
                        reason="Outra vez",
                    )
        finally:
            await engine.dispose()

    asyncio.run(run())
