from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.lifecycle import ensure_module_instance
from app.platform.models import (
    AutomationTask,
    DeliveryOutbox,
    ModuleMigrationRun,
    PanelInstance,
    PanelState,
    WorkState,
)
from app.platform.registry import module_registry
from app.platform.schemas import HealthCheckOut


def check(status: str, code: str, summary: str, detail: str = "", action: str = "") -> HealthCheckOut:
    return HealthCheckOut(
        status=status,
        code=code,
        summary=summary,
        detail=detail,
        action=action,
        checked_at=datetime.now(timezone.utc),
    )


async def platform_health(session: AsyncSession) -> list[HealthCheckOut]:
    checks: list[HealthCheckOut] = []
    try:
        await session.execute(text("SELECT 1"))
        checks.append(check("OK", "platform.database", "PostgreSQL/SQLAlchemy acessivel."))
    except Exception:
        await session.rollback()
        checks.append(check("ERROR", "platform.database", "Banco indisponivel.", action="Verifique a conexao."))
        checks.append(check("UNKNOWN", "platform.redis", "Redis nao verificado porque o banco esta indisponivel."))
        return checks
    try:
        revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
        checks.append(
            check(
                "OK" if revision else "WARNING",
                "platform.migrations",
                f"Revisao Alembic: {revision or 'ausente'}.",
                action="Execute o upgrade aditivo antes de ativar o runtime novo."
                if not revision
                else "",
            )
        )
    except Exception:
        await session.rollback()
        checks.append(
            check(
                "WARNING",
                "platform.migrations",
                "Nao foi possivel ler a revisao Alembic.",
                action="Verifique alembic_version.",
            )
        )
    now = datetime.now(timezone.utc)
    overdue = int(
        await session.scalar(
            select(func.count()).select_from(AutomationTask).where(
                AutomationTask.state.in_([WorkState.pending, WorkState.retry]),
                AutomationTask.due_at < now,
            )
        )
        or 0
    )
    checks.append(
        check(
            "WARNING" if overdue else "OK",
            "platform.automation",
            f"{overdue} tarefa(s) atrasada(s).",
            action="Verifique o AutomationCoordinator." if overdue else "",
        )
    )
    checks.append(
        check(
            "UNKNOWN",
            "platform.redis",
            "Redis nao e fonte de verdade e ainda nao possui probe no backend.",
            action="Adicionar probe quando cache/wakeup forem ativados.",
        )
    )
    return checks


async def module_health(
    session: AsyncSession, *, guild_id: str, module_key: str
) -> list[HealthCheckOut]:
    definition = module_registry.get(module_key)
    if definition is None:
        return [check("ERROR", "module.unknown", "Modulo nao registrado.")]
    instance = await ensure_module_instance(session, guild_id=guild_id, module_key=module_key)
    checks = [
        check(
            "OK" if instance.last_error is None else "ERROR",
            "module.runtime",
            f"Runtime {instance.runtime_mode.value}; lifecycle {instance.lifecycle.value}.",
            detail=instance.last_error or "",
        )
    ]
    if definition.configuration is not None:
        checks.append(
            check(
                "OK" if instance.published_config_version_id else "WARNING",
                "module.configuration",
                "Configuracao publicada." if instance.published_config_version_id else "Sem configuracao publicada.",
                action="Publique um rascunho valido." if not instance.published_config_version_id else "",
            )
        )
    missing_panels = int(
        await session.scalar(
            select(func.count()).select_from(PanelInstance).where(
                PanelInstance.guild_id == guild_id,
                PanelInstance.module_key == module_key,
                PanelInstance.state.in_([PanelState.missing, PanelState.error]),
            )
        )
        or 0
    )
    checks.append(
        check(
            "WARNING" if missing_panels else "OK",
            "module.panels",
            f"{missing_panels} painel(is) ausente(s) ou com erro.",
            action="Reconcilie os paineis pela Central." if missing_panels else "",
        )
    )
    failed_work = int(
        await session.scalar(
            select(func.count()).select_from(AutomationTask).where(
                AutomationTask.guild_id == guild_id,
                AutomationTask.module_key == module_key,
                AutomationTask.state == WorkState.failed,
            )
        )
        or 0
    )
    failed_delivery = int(
        await session.scalar(
            select(func.count()).select_from(DeliveryOutbox).where(
                DeliveryOutbox.guild_id == guild_id,
                DeliveryOutbox.module_key == module_key,
                DeliveryOutbox.state == WorkState.failed,
            )
        )
        or 0
    )
    checks.append(
        check(
            "ERROR" if failed_work or failed_delivery else "OK",
            "module.background_work",
            f"{failed_work} job(s) e {failed_delivery} entrega(s) com falha.",
            action="Inspecione runs e tentativas." if failed_work or failed_delivery else "",
        )
    )
    latest_migration = (
        await session.execute(
            select(ModuleMigrationRun)
            .where(
                ModuleMigrationRun.guild_id == guild_id,
                ModuleMigrationRun.module_key == module_key,
            )
            .order_by(ModuleMigrationRun.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    checks.append(
        check(
            "OK" if latest_migration is None or not latest_migration.errors else "ERROR",
            "module.migration",
            "Nenhuma migracao exigida." if latest_migration is None else f"Migracao {latest_migration.state.value}.",
        )
    )
    for contributor in definition.health_checks:
        try:
            checks.extend(HealthCheckOut.model_validate(item) for item in await contributor(session, guild_id))
        except Exception:
            checks.append(check("ERROR", f"module.health.{contributor.key}", "Health check do modulo falhou."))
    return checks
