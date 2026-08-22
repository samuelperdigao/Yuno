import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "bot"))

import app.models  # noqa: E402,F401 -- registra legado e plataforma no Base
from app.domain_modules.farm.definition import MODULE_DEFINITION as FARM_DEFINITION  # noqa: E402
from app.api.platform.dependencies import require_platform_admin  # noqa: E402
from app.db import Base  # noqa: E402
from app.platform.audit import write_audit  # noqa: E402
from app.platform.automation import claim_tasks, complete_task, schedule_task  # noqa: E402
from app.platform.configuration import (  # noqa: E402
    effective_configuration,
    get_or_create_draft,
    publish,
    rollback,
    save_draft,
)
from app.platform.contracts import (  # noqa: E402
    ActionContract,
    CapabilityDefinition,
    ConfigurationContract,
    ConfigurationField,
    ConfigurationFieldType,
    JobDefinition,
    LifecyclePolicy,
    MigrationContract,
    ModuleDefinition,
    ModuleDependency,
    ModuleManifest,
    NotificationDefinition,
    PanelContract,
)
from app.platform.interactions import begin_interaction, finish_interaction  # noqa: E402
from app.platform.lifecycle import ensure_module_instance, update_lifecycle  # noqa: E402
from app.platform.migrations import (  # noqa: E402
    cutover,
    rollback_cutover,
    start_migration,
    update_migration,
)
from app.platform.models import (  # noqa: E402
    AuditEntry,
    MigrationState,
    ModuleLifecycle,
    PanelState,
    RuntimeMode,
    WorkState,
)
from app.platform.outbox import (  # noqa: E402
    claim_deliveries,
    complete_delivery,
    enqueue_delivery,
)
from app.platform.panels import ensure_panel, get_panel, update_panel  # noqa: E402
from app.platform.permissions import authorize  # noqa: E402
from app.platform.registry import ModuleRegistry, discover_domain_modules, module_registry  # noqa: E402
from app.platform.schemas import ActorContextIn, PermissionGrantIn  # noqa: E402
from yuno_bot.platform.registry import UIRegistry, discover_ui_modules, verify_backend_manifest  # noqa: E402
from yuno_bot.platform import coordinator as platform_coordinator  # noqa: E402
from yuno_bot.platform.contracts import InteractionResult, ModuleUIAdapter  # noqa: E402
from yuno_bot.platform.coordinator import PlatformCoordinator  # noqa: E402
from yuno_bot.platform.router import InteractionRouter, custom_id, parse_custom_id  # noqa: E402
from yuno_bot.domain_modules.farm import MODULE_UI as FARM_UI  # noqa: E402


class SyntheticMigration:
    key = "foundation_v1"

    async def inventory(self, session, guild_id: str) -> dict:
        del session
        return {"guild_id": guild_id, "rows": 0}

    async def validate(self, session, guild_id: str) -> list[str]:
        del session
        return []


def synthetic_definition() -> ModuleDefinition:
    return ModuleDefinition(
        manifest=ModuleManifest(
            key="foundation_test",
            name="Foundation Test",
            description="Modulo sintetico usado apenas pelos testes da plataforma.",
            domain_version="1",
            runtime_modes=("legacy", "shadow", "domain"),
        ),
        configuration=ConfigurationContract(
            schema_version=1,
            fields=(
                ConfigurationField(
                    "timezone",
                    "Timezone",
                    ConfigurationFieldType.timezone,
                    required=True,
                    default="America/Sao_Paulo",
                ),
                ConfigurationField(
                    "color",
                    "Cor",
                    ConfigurationFieldType.color,
                    default="#112233",
                ),
                ConfigurationField(
                    "channel_id",
                    "Canal",
                    ConfigurationFieldType.channel,
                    required=True,
                ),
            ),
        ),
        capabilities=(
            CapabilityDefinition("foundation_test.manage", administrative=True),
            CapabilityDefinition(
                "foundation_test.use",
                resource_scoped=True,
                allow_resource_owner=True,
                denial_reason="Uso nao autorizado.",
            ),
        ),
        lifecycle=LifecyclePolicy(requires_published_configuration=True),
        panels=(PanelContract("public", recovery_policy="automatic"),),
        actions=(ActionContract("open", "foundation_test.use", panel_key="public"),),
        jobs=(JobDefinition("expire", max_attempts=3),),
        notifications=(NotificationDefinition("log", ("channel",)),),
        migration=SyntheticMigration(),
    )


def test_new_registry_discovers_only_domain_first_modules() -> None:
    definitions = discover_domain_modules().all()
    assert [item.manifest.key for item in definitions] == ["meta", "registration", "tags"]
    adapters = discover_ui_modules().all()
    assert [item.module_key for item in adapters] == ["meta", "registration", "tags"]
    by_key = {item.module_key: item for item in adapters}
    assert FARM_DEFINITION.manifest.released is False
    assert FARM_UI.released is False
    assert {item.key for item in by_key["registration"].panels} == {"public", "review"}
    assert {item.key for item in by_key["registration"].jobs} == {
        "registration.processing.recover",
        "registration.panel.reconcile",
    }
    assert by_key["tags"].panels == ()
    assert {item.key for item in by_key["tags"].jobs} == {
        "tags.member.sync",
        "tags.run.plan",
        "tags.run.finalize",
        "tags.retention",
    }
    legacy_keys = {
        "farm_tickets", "set", "ticket", "ausencia", "parceria", "producao"
    }
    assert legacy_keys.isdisjoint(item.manifest.key for item in definitions)
    assert verify_backend_manifest({"modules": []}, UIRegistry()) == []
    ui = UIRegistry()
    ui.register(ModuleUIAdapter(module_key="new_module", contract_version=2))
    assert verify_backend_manifest(
        {"modules": [{"key": "new_module", "contract_version": 1}]}, ui
    ) == ["new_module: versao de contrato incompativel"]

    platform_sources = list((ROOT / "backend" / "app" / "platform").glob("*.py"))
    platform_sources += list((ROOT / "bot" / "yuno_bot" / "platform").glob("*.py"))
    source = "\n".join(path.read_text(encoding="utf-8") for path in platform_sources)
    assert "yuno_bot.commands" not in source
    assert "farm_tickets" not in source


def test_module_contracts_are_composable_and_dependency_safe() -> None:
    registry = ModuleRegistry()
    simple = ModuleDefinition(
        manifest=ModuleManifest(key="simple", name="Simple", description="Sem contratos opcionais.")
    )
    registry.register(simple)
    assert registry.get("simple").configuration is None
    assert registry.get("simple").panels == ()
    public_contract = registry.manifests()[0]
    assert public_contract["configuration"] is None
    assert public_contract["capabilities"] == []
    with pytest.raises(ValueError, match="depende"):
        registry.register(
            ModuleDefinition(
                manifest=ModuleManifest(
                    key="broken",
                    name="Broken",
                    description="Broken",
                    dependencies=(ModuleDependency("missing"),),
                )
            )
        )

    cyclic = ModuleRegistry()
    with pytest.raises(ValueError, match="Ciclo"):
        cyclic.register_many(
            [
                ModuleDefinition(
                    manifest=ModuleManifest(
                        key="a", name="A", description="A", dependencies=(ModuleDependency("b"),)
                    )
                ),
                ModuleDefinition(
                    manifest=ModuleManifest(
                        key="b", name="B", description="B", dependencies=(ModuleDependency("a"),)
                    )
                ),
            ]
        )
    assert cyclic.all() == ()


def test_configuration_field_types_are_enforced_without_a_free_dsl() -> None:
    contract = synthetic_definition().configuration
    assert contract is not None
    assert contract.validate(
        {"timezone": "America/Sao_Paulo", "color": "#AABBCC", "channel_id": "123"}
    ) == []
    errors = contract.validate(
        {"timezone": "Nao/Existe", "color": "amarelo", "channel_id": 123, "extra": True}
    )
    assert len(errors) == 4


def test_platform_services_form_a_tenant_safe_vertical_foundation() -> None:
    async def scenario() -> None:
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        definition = synthetic_definition()
        module_registry.register(definition)
        try:
            async with sessions() as session:
                draft = await get_or_create_draft(
                    session, guild_id="guild-a", module_key="foundation_test"
                )
                await session.commit()
                admin_actor = ActorContextIn(
                    guild_id="guild-a",
                    user_id="10",
                    discord_permissions=["manage_guild"],
                    correlation_id="admin-1",
                )
                assert await require_platform_admin(
                    session,
                    guild_id="guild-a",
                    actor_header="10",
                    actor=admin_actor,
                ) == "admin-1"
                with pytest.raises(HTTPException):
                    await require_platform_admin(
                        session,
                        guild_id="guild-a",
                        actor_header="11",
                        actor=admin_actor,
                    )
                assert draft.data == {"timezone": "America/Sao_Paulo", "color": "#112233"}
                saved = await save_draft(
                    session,
                    guild_id="guild-a",
                    module_key="foundation_test",
                    actor_id="10",
                    expected_revision=0,
                    expected_published_version=0,
                    schema_version=1,
                    data={
                        "timezone": "America/Sao_Paulo",
                        "color": "#445566",
                        "channel_id": "100",
                    },
                    correlation_id="config-1",
                )
                with pytest.raises(HTTPException) as conflict:
                    await save_draft(
                        session,
                        guild_id="guild-a",
                        module_key="foundation_test",
                        actor_id="11",
                        expected_revision=0,
                        expected_published_version=0,
                        schema_version=1,
                        data=saved.data,
                        correlation_id="config-conflict",
                    )
                assert conflict.value.status_code == 409
                await session.rollback()

                version = await publish(
                    session,
                    guild_id="guild-a",
                    module_key="foundation_test",
                    actor_id="10",
                    expected_revision=1,
                    expected_published_version=0,
                    grants=[
                        PermissionGrantIn(
                            capability="foundation_test.use",
                            subject_type="role",
                            subject_id="9",
                        )
                    ],
                    correlation_id="publish-1",
                )
                assert version.version == 1
                effective = await effective_configuration(
                    session, guild_id="guild-a", module_key="foundation_test"
                )
                assert effective is not None and effective.data["channel_id"] == "100"

                allowed = await authorize(
                    session,
                    guild_id="guild-a",
                    module_key="foundation_test",
                    capability_key="foundation_test.use",
                    actor=ActorContextIn(
                        guild_id="guild-a", user_id="20", role_ids=["9"], correlation_id="permission-1"
                    ),
                )
                assert allowed.allowed
                denied_other_guild = await authorize(
                    session,
                    guild_id="guild-b",
                    module_key="foundation_test",
                    capability_key="foundation_test.use",
                    actor=ActorContextIn(
                        guild_id="guild-b", user_id="20", role_ids=["9"], correlation_id="permission-2"
                    ),
                )
                assert not denied_other_guild.allowed
                owner = await authorize(
                    session,
                    guild_id="guild-a",
                    module_key="foundation_test",
                    capability_key="foundation_test.use",
                    actor=ActorContextIn(
                        guild_id="guild-a", user_id="20", resource_owner_id="20", correlation_id="permission-3"
                    ),
                    resource_id="resource-1",
                )
                assert owner.allowed

                instance = await update_lifecycle(
                    session,
                    guild_id="guild-a",
                    module_key="foundation_test",
                    actor_id="10",
                    expected=ModuleLifecycle.inactive,
                    target=ModuleLifecycle.active,
                    reason=None,
                    correlation_id="activate-1",
                )
                assert instance.lifecycle == ModuleLifecycle.active

                panel = await ensure_panel(
                    session,
                    guild_id="guild-a",
                    module_key="foundation_test",
                    panel_key="public",
                    resource_type="cycle",
                    resource_id="1",
                    definition_version=1,
                    recovery_policy="automatic",
                    actor_id="10",
                    correlation_id="panel-1",
                )
                same_panel = await ensure_panel(
                    session,
                    guild_id="guild-a",
                    module_key="foundation_test",
                    panel_key="public",
                    resource_type="cycle",
                    resource_id="1",
                    definition_version=1,
                    recovery_policy="automatic",
                    actor_id="10",
                    correlation_id="panel-2",
                )
                assert same_panel.id == panel.id
                panel = await update_panel(
                    session,
                    guild_id="guild-a",
                    panel_id=panel.id,
                    actor_id="10",
                    expected_render_revision=0,
                    state=PanelState.ready,
                    channel_id=None,
                    message_id=None,
                    config_version=None,
                    last_error=None,
                    verified=False,
                    correlation_id="panel-3",
                )
                panel = await update_panel(
                    session,
                    guild_id="guild-a",
                    panel_id=panel.id,
                    actor_id="10",
                    expected_render_revision=1,
                    state=PanelState.published,
                    channel_id="100",
                    message_id="200",
                    config_version=1,
                    last_error=None,
                    verified=True,
                    correlation_id="panel-4",
                )
                assert panel.state.value == "published"
                assert await get_panel(session, guild_id="guild-b", panel_id=panel.id) is None

                due = datetime.now(timezone.utc)
                task = await schedule_task(
                    session,
                    guild_id="guild-a",
                    module_key="foundation_test",
                    job_key="expire",
                    resource_type="cycle",
                    resource_id="1",
                    payload={},
                    due_at=due,
                    idempotency_key="job-1",
                    correlation_id="job-correlation",
                    max_attempts=None,
                )
                duplicate_task = await schedule_task(
                    session,
                    guild_id="guild-a",
                    module_key="foundation_test",
                    job_key="expire",
                    resource_type="cycle",
                    resource_id="1",
                    payload={"ignored": True},
                    due_at=due,
                    idempotency_key="job-1",
                    correlation_id="job-correlation",
                    max_attempts=None,
                )
                assert duplicate_task.id == task.id
                claimed = await claim_tasks(
                    session, worker_id="worker-1", limit=10, lease_seconds=60
                )
                assert [item.id for item in claimed] == [task.id]
                assert await claim_tasks(
                    session, worker_id="worker-2", limit=10, lease_seconds=60
                ) == []
                await complete_task(
                    session,
                    guild_id="guild-a",
                    task_id=task.id,
                    worker_id="worker-1",
                    result={"ok": True},
                )

                delivery = await enqueue_delivery(
                    session,
                    guild_id="guild-a",
                    module_key="foundation_test",
                    renderer_key="log",
                    destination_type="channel",
                    destination_id="100",
                    resource_type="cycle",
                    resource_id="1",
                    payload={},
                    priority=100,
                    available_at=due,
                    idempotency_key="delivery-1",
                    correlation_id="delivery-correlation",
                    max_attempts=3,
                )
                assert (
                    await enqueue_delivery(
                        session,
                        guild_id="guild-a",
                        module_key="foundation_test",
                        renderer_key="log",
                        destination_type="channel",
                        destination_id="100",
                        resource_type="cycle",
                        resource_id="1",
                        payload={},
                        priority=100,
                        available_at=due,
                        idempotency_key="delivery-1",
                        correlation_id="delivery-correlation",
                        max_attempts=3,
                    )
                ).id == delivery.id
                claimed_delivery = await claim_deliveries(
                    session, worker_id="worker-1", limit=10, lease_seconds=60
                )
                assert [item.id for item in claimed_delivery] == [delivery.id]
                await complete_delivery(
                    session,
                    guild_id="guild-a",
                    delivery_id=delivery.id,
                    worker_id="worker-1",
                    external_id="discord-message-1",
                )

                receipt, duplicate = await begin_interaction(
                    session,
                    guild_id="guild-a",
                    interaction_id="999",
                    module_key="foundation_test",
                    action_key="open",
                    resource_type="cycle",
                    resource_id="1",
                    correlation_id="interaction-1",
                )
                assert not duplicate
                repeated, duplicate = await begin_interaction(
                    session,
                    guild_id="guild-a",
                    interaction_id="999",
                    module_key="foundation_test",
                    action_key="open",
                    resource_type="cycle",
                    resource_id="1",
                    correlation_id="interaction-1",
                )
                assert duplicate and repeated.id == receipt.id
                finished = await finish_interaction(
                    session,
                    guild_id="guild-a",
                    receipt_id=receipt.id,
                    result={"ok": True},
                    error=None,
                )
                assert finished is not None and finished.state == WorkState.succeeded

                rolled = await rollback(
                    session,
                    guild_id="guild-a",
                    module_key="foundation_test",
                    actor_id="10",
                    source_version=1,
                    expected_published_version=1,
                    correlation_id="rollback-1",
                )
                assert rolled.version == 2 and rolled.source_version == 1

                await write_audit(
                    session,
                    guild_id="guild-a",
                    module_key="foundation_test",
                    action="security.redaction_test",
                    resource_type="test",
                    correlation_id="audit-redaction",
                    after={"api_token": "must-not-leak", "safe": "visible"},
                )
                await session.commit()
                audit = (
                    await session.execute(
                        select(AuditEntry).where(AuditEntry.correlation_id == "audit-redaction")
                    )
                ).scalar_one()
                assert audit.after == {"api_token": "[REDACTED]", "safe": "visible"}

                migration = await start_migration(
                    session,
                    guild_id="guild-a",
                    module_key="foundation_test",
                    migration_key="foundation_v1",
                    target_mode=RuntimeMode.domain,
                    actor_id="10",
                    correlation_id="migration-1",
                )
                migration = await update_migration(
                    session,
                    guild_id="guild-a",
                    run_id=migration.id,
                    actor_id="10",
                    state=MigrationState.validating,
                    checkpoint={"incompatible_writes": False},
                    counts={"source": 0, "target": 0},
                    checksum="empty",
                    warnings=[],
                    errors=[],
                    correlation_id="migration-2",
                )
                migration = await update_migration(
                    session,
                    guild_id="guild-a",
                    run_id=migration.id,
                    actor_id="10",
                    state=MigrationState.ready,
                    checkpoint={"incompatible_writes": False},
                    counts={"source": 0, "target": 0},
                    checksum="empty",
                    warnings=[],
                    errors=[],
                    correlation_id="migration-ready",
                )
                await cutover(
                    session,
                    guild_id="guild-a",
                    run_id=migration.id,
                    actor_id="10",
                    correlation_id="migration-3",
                )
                current = await ensure_module_instance(
                    session, guild_id="guild-a", module_key="foundation_test"
                )
                assert current.runtime_mode == RuntimeMode.domain
                await rollback_cutover(
                    session,
                    guild_id="guild-a",
                    run_id=migration.id,
                    actor_id="10",
                    correlation_id="migration-4",
                )
                assert current.runtime_mode == RuntimeMode.legacy
        finally:
            module_registry.unregister("foundation_test")
            await engine.dispose()

    asyncio.run(scenario())


def test_interaction_ids_are_versioned_restart_safe_and_resource_free() -> None:
    value = custom_id("foundation_test", "public", "open")
    assert value == "yuno:v1:foundation_test:public:open"
    assert parse_custom_id(value) == {
        "version": 1,
        "module": "foundation_test",
        "surface": "public",
        "action": "open",
    }
    assert "resource" not in value
    assert parse_custom_id("legacy:button") is None


def test_coordinator_keeps_polling_with_python_310_asyncio_timeout(monkeypatch) -> None:
    class LegacyAsyncioTimeoutError(Exception):
        pass

    class Bot:
        async def wait_until_ready(self) -> None:
            return None

    class Registry:
        def all(self) -> list[SimpleNamespace]:
            return [SimpleNamespace(jobs=(object(),), deliveries=())]

    coordinator = PlatformCoordinator(Bot(), object(), Registry())
    calls: list[int] = []

    async def run_once() -> None:
        calls.append(len(calls) + 1)
        if len(calls) == 2:
            coordinator._stopping.set()

    async def wait_for(awaitable, *, timeout: float) -> None:
        del timeout
        awaitable.close()
        raise LegacyAsyncioTimeoutError

    fake_asyncio = SimpleNamespace(
        TimeoutError=LegacyAsyncioTimeoutError,
        wait_for=wait_for,
    )
    monkeypatch.setattr(platform_coordinator, "asyncio", fake_asyncio)
    monkeypatch.setattr(coordinator, "run_once", run_once)

    asyncio.run(coordinator._run())

    assert calls == [1, 2]


def test_coordinator_keeps_polling_after_unexpected_cycle_failure(monkeypatch) -> None:
    class LegacyAsyncioTimeoutError(Exception):
        pass

    errors: list[str] = []

    class Log:
        def exception(self, message: str) -> None:
            errors.append(message)

    class Bot:
        log = Log()

        async def wait_until_ready(self) -> None:
            return None

    class Registry:
        def all(self) -> list[SimpleNamespace]:
            return [SimpleNamespace(jobs=(object(),), deliveries=())]

    coordinator = PlatformCoordinator(Bot(), object(), Registry())
    calls: list[int] = []

    async def run_once() -> None:
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            raise RuntimeError("falha dupla ao registrar uma entrega")
        coordinator._stopping.set()

    async def wait_for(awaitable, *, timeout: float) -> None:
        del timeout
        awaitable.close()
        raise LegacyAsyncioTimeoutError

    fake_asyncio = SimpleNamespace(
        CancelledError=asyncio.CancelledError,
        TimeoutError=LegacyAsyncioTimeoutError,
        wait_for=wait_for,
    )
    monkeypatch.setattr(platform_coordinator, "asyncio", fake_asyncio)
    monkeypatch.setattr(coordinator, "run_once", run_once)

    asyncio.run(coordinator._run())

    assert calls == [1, 2]
    assert errors == [
        "Falha inesperada no ciclo da Yuno Platform; o worker continuara ativo"
    ]


def test_router_omits_empty_discord_response_fields() -> None:
    sent: list[dict] = []

    class Response:
        def is_done(self) -> bool:
            return False

        async def send_message(self, **kwargs) -> None:
            sent.append(kwargs)

    interaction = SimpleNamespace(response=Response())

    asyncio.run(
        InteractionRouter._render(interaction, InteractionResult(content="Tudo certo."))
    )

    assert sent == [{"content": "Tudo certo.", "ephemeral": True}]
