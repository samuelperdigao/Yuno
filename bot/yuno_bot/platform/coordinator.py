from __future__ import annotations

import asyncio
import socket

from yuno_bot.platform.registry import UIRegistry, ui_registry
from yuno_bot.platform.contracts import RetryableJobError


class PlatformCoordinator:
    """Executa jobs e entregas duraveis declarados por modulos domain-first."""

    def __init__(self, bot, api, registry: UIRegistry | None = None) -> None:
        self.bot = bot
        self.api = api
        self.registry = registry or ui_registry
        self.worker_id = f"discord:{socket.gethostname()}:{id(self)}"
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    @property
    def has_handlers(self) -> bool:
        return any(adapter.jobs or adapter.deliveries for adapter in self.registry.all())

    def start(self) -> None:
        if not self.has_handlers or self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="yuno-platform-coordinator")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run(self) -> None:
        await self.bot.wait_until_ready()
        while not self._stopping.is_set():
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.bot.log.exception(
                    "Falha inesperada no ciclo da Yuno Platform; o worker continuara ativo"
                )
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass

    async def run_once(self) -> None:
        try:
            tasks = await self.api.claim_tasks(self.worker_id)
            deliveries = await self.api.claim_deliveries(self.worker_id)
        except Exception:
            self.bot.log.exception("Falha ao buscar trabalho da Yuno Platform")
            return
        for item in tasks:
            handler = self.registry.job(item["module_key"], item["key"])
            if handler is None:
                await self.api.fail_task(item, self.worker_id, "Handler de job nao registrado no bot.")
                continue
            try:
                result = await handler.handler(self.bot, self.api, item)
                await self.api.complete_task(item, self.worker_id, result)
            except RetryableJobError as exc:
                self.bot.log.warning("Job %s:%s sera repetido", item["module_key"], item["key"])
                await self.api.fail_task(
                    item, self.worker_id, str(exc), retry_at=exc.retry_at
                )
            except Exception:
                self.bot.log.exception("Falha no job %s:%s", item["module_key"], item["key"])
                await self.api.fail_task(item, self.worker_id, "Falha no handler do job.")
        for item in deliveries:
            renderer = self.registry.delivery(item["module_key"], item["key"])
            if renderer is None:
                await self.api.fail_delivery(item, self.worker_id, "Renderer de entrega nao registrado.")
                continue
            try:
                external_id = await renderer.handler(self.bot, item)
                await self.api.complete_delivery(item, self.worker_id, external_id)
            except Exception:
                self.bot.log.exception("Falha na entrega %s:%s", item["module_key"], item["key"])
                await self.api.fail_delivery(item, self.worker_id, "Falha no renderer da entrega.")
