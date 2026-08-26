from __future__ import annotations

import asyncio
import socket

from yuno_bot.platform.contracts import RetryableJobError
from yuno_bot.platform.registry import UIRegistry, ui_registry

# `error` de fail_task/fail_delivery aceita 2000 caracteres no backend.
ERROR_MAX_LENGTH = 2000


def describe_error(exc: BaseException) -> str:
    """Descreve `exc` para gravar em `last_error`.

    Gravar um texto generico apagava a unica pista que sobrava: o traceback vai
    para o journal do bot, mas quem olha a fila ve so a linha do banco. Foi
    assim que cinco jobs ficaram com "Falha no handler do job." e exigiram
    reproduzir tudo a mao para descobrir que o backend respondia 422.

    Para erro HTTP o corpo da resposta vai junto -- e nele que o FastAPI diz
    qual campo recusou.
    """
    detalhe = f"{type(exc).__name__}: {exc}"
    corpo = getattr(getattr(exc, "response", None), "text", None)
    if corpo:
        detalhe = f"{detalhe} | corpo: {corpo}"
    return detalhe[:ERROR_MAX_LENGTH]


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
        tasks: list[dict] = []
        deliveries: list[dict] = []
        try:
            tasks = await self.api.claim_tasks(self.worker_id)
        except Exception:
            self.bot.log.exception("Falha ao buscar jobs da Yuno Platform")
        try:
            deliveries = await self.api.claim_deliveries(self.worker_id)
        except Exception:
            self.bot.log.exception("Falha ao buscar entregas da Yuno Platform")
        for item in tasks:
            handler = self.registry.job(item["module_key"], item["key"])
            if handler is None:
                await self.api.fail_task(item, self.worker_id, "Handler de job não registrado no bot.")
                continue
            try:
                result = await handler.handler(self.bot, self.api, item)
                await self.api.complete_task(item, self.worker_id, result)
            except RetryableJobError as exc:
                self.bot.log.warning("Job %s:%s será repetido", item["module_key"], item["key"])
                await self.api.fail_task(
                    item, self.worker_id, str(exc), retry_at=exc.retry_at
                )
            except Exception as exc:
                self.bot.log.exception("Falha no job %s:%s", item["module_key"], item["key"])
                await self.api.fail_task(item, self.worker_id, describe_error(exc))
        for item in deliveries:
            renderer = self.registry.delivery(item["module_key"], item["key"])
            if renderer is None:
                await self.api.fail_delivery(item, self.worker_id, "Renderer de entrega não registrado.")
                continue
            try:
                external_id = await renderer.handler(self.bot, item)
                await self.api.complete_delivery(item, self.worker_id, external_id)
            except Exception as exc:
                self.bot.log.exception("Falha na entrega %s:%s", item["module_key"], item["key"])
                await self.api.fail_delivery(item, self.worker_id, describe_error(exc))
