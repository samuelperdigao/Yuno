from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

from yuno_bot.platform.contracts import (
    ActionDefinition,
    AdminActionDefinition,
    DeliveryRendererDefinition,
    JobHandlerDefinition,
    ModuleUIAdapter,
    PanelDefinition,
)


class UIRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, ModuleUIAdapter] = {}

    def register(self, adapter: ModuleUIAdapter) -> None:
        if adapter.module_key in self._adapters:
            raise ValueError(f"Adapter UI duplicado: {adapter.module_key}.")
        self._validate(adapter)
        self._adapters[adapter.module_key] = adapter

    def unregister(self, module_key: str) -> None:
        self._adapters.pop(module_key, None)

    def get(self, module_key: str) -> ModuleUIAdapter | None:
        return self._adapters.get(module_key)

    def all(self) -> tuple[ModuleUIAdapter, ...]:
        return tuple(self._adapters[key] for key in sorted(self._adapters))

    def action(self, module_key: str, surface: str, action_key: str) -> ActionDefinition | None:
        adapter = self.get(module_key)
        if adapter is None:
            return None
        return next(
            (item for item in adapter.actions if item.surface == surface and item.key == action_key),
            None,
        )

    def admin_action(self, module_key: str, action_key: str) -> AdminActionDefinition | None:
        adapter = self.get(module_key)
        if adapter is None:
            return None
        return next((item for item in adapter.admin_actions if item.key == action_key), None)

    def panel(self, module_key: str, panel_key: str) -> PanelDefinition | None:
        adapter = self.get(module_key)
        return next((item for item in adapter.panels if item.key == panel_key), None) if adapter else None

    def job(self, module_key: str, job_key: str) -> JobHandlerDefinition | None:
        adapter = self.get(module_key)
        return next((item for item in adapter.jobs if item.key == job_key), None) if adapter else None

    def delivery(self, module_key: str, renderer_key: str) -> DeliveryRendererDefinition | None:
        adapter = self.get(module_key)
        return next((item for item in adapter.deliveries if item.key == renderer_key), None) if adapter else None

    def discover(self, package: ModuleType) -> None:
        for info in pkgutil.iter_modules(package.__path__):
            if not info.ispkg:
                continue
            imported = importlib.import_module(f"{package.__name__}.{info.name}")
            adapter = getattr(imported, "MODULE_UI", None)
            if adapter is None:
                continue
            if not isinstance(adapter, ModuleUIAdapter):
                raise TypeError(f"{imported.__name__}.MODULE_UI deve ser ModuleUIAdapter.")
            if adapter.module_key != info.name:
                raise ValueError("A pasta do adapter UI deve ter a mesma chave do modulo.")
            if not adapter.released:
                continue
            if self.get(adapter.module_key) is adapter:
                continue
            self.register(adapter)

    @staticmethod
    def _validate(adapter: ModuleUIAdapter) -> None:
        groups = {
            "pagina": [item.key for item in adapter.admin_pages],
            "acao administrativa": [item.key for item in adapter.admin_actions],
            "painel": [item.key for item in adapter.panels],
            "acao": [(item.surface, item.key) for item in adapter.actions],
            "job": [item.key for item in adapter.jobs],
            "delivery": [item.key for item in adapter.deliveries],
        }
        for label, keys in groups.items():
            if len(keys) != len(set(keys)):
                raise ValueError(f"Chave de {label} duplicada em '{adapter.module_key}'.")
        panels = {item.key for item in adapter.panels}
        for action in adapter.actions:
            if action.panel_key and action.panel_key not in panels:
                raise ValueError(
                    f"Acao '{action.key}' referencia painel UI inexistente '{action.panel_key}'."
                )


ui_registry = UIRegistry()


def discover_ui_modules() -> UIRegistry:
    from yuno_bot import domain_modules

    ui_registry.discover(domain_modules)
    return ui_registry


def verify_backend_manifest(manifest: dict, registry: UIRegistry | None = None) -> list[str]:
    registry = registry or ui_registry
    backend = {item["key"]: item for item in manifest.get("modules", [])}
    issues: list[str] = []
    for adapter in registry.all():
        remote = backend.get(adapter.module_key)
        if remote is None:
            issues.append(f"{adapter.module_key}: ausente no backend")
        elif int(remote.get("contract_version", 0)) != adapter.contract_version:
            issues.append(f"{adapter.module_key}: versao de contrato incompativel")
    for module_key in backend:
        if registry.get(module_key) is None:
            issues.append(f"{module_key}: adapter Discord ausente")
    return sorted(issues)
