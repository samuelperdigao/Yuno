from __future__ import annotations

import importlib
import pkgutil
from dataclasses import asdict
from types import ModuleType

from app.platform.contracts import ModuleDefinition


PLATFORM_CONTRACT_VERSION = 1


class ModuleRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, ModuleDefinition] = {}

    def register(self, definition: ModuleDefinition, *, replace: bool = False) -> None:
        key = definition.manifest.key
        if not key or key != key.lower().replace(" ", "_"):
            raise ValueError("A chave do modulo deve ser snake_case minuscula.")
        if key in self._definitions and not replace:
            raise ValueError(f"Modulo duplicado: {key}.")
        self._validate_local_keys(definition)
        previous = self._definitions.get(key)
        self._definitions[key] = definition
        try:
            self.validate_dependencies()
        except Exception:
            if previous is not None:
                self._definitions[key] = previous
            else:
                self._definitions.pop(key, None)
            raise

    def register_many(self, definitions: list[ModuleDefinition]) -> None:
        keys: list[str] = []
        for definition in definitions:
            key = definition.manifest.key
            if key in self._definitions or key in keys:
                raise ValueError(f"Modulo duplicado: {key}.")
            if not key or key != key.lower().replace(" ", "_"):
                raise ValueError("A chave do modulo deve ser snake_case minuscula.")
            self._validate_local_keys(definition)
            keys.append(key)
        for definition in definitions:
            key = definition.manifest.key
            self._definitions[key] = definition
        try:
            self.validate_dependencies()
        except Exception:
            for key in keys:
                self._definitions.pop(key, None)
            raise

    def unregister(self, key: str) -> None:
        self._definitions.pop(key, None)

    def get(self, key: str) -> ModuleDefinition | None:
        return self._definitions.get(key)

    def all(self) -> tuple[ModuleDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions))

    def manifests(self) -> list[dict]:
        result: list[dict] = []
        for definition in self.all():
            item = asdict(definition.manifest)
            item.update(
                {
                    "configuration": None
                    if definition.configuration is None
                    else {
                        "schema_version": definition.configuration.schema_version,
                        "fields": [asdict(field) for field in definition.configuration.fields],
                        "defaults": definition.configuration.defaults(),
                    },
                    "capabilities": [asdict(value) for value in definition.capabilities],
                    "lifecycle": asdict(definition.lifecycle),
                    "panels": [asdict(value) for value in definition.panels],
                    "actions": [asdict(value) for value in definition.actions],
                    "jobs": [asdict(value) for value in definition.jobs],
                    "notifications": [asdict(value) for value in definition.notifications],
                    "health_checks": [value.key for value in definition.health_checks],
                    "has_migration": definition.migration is not None,
                }
            )
            result.append(item)
        return result

    def discover(self, package: ModuleType) -> None:
        """Descobre somente modulos domain-first no namespace informado."""
        discovered: list[ModuleDefinition] = []
        for info in pkgutil.iter_modules(package.__path__):
            if not info.ispkg:
                continue
            imported = importlib.import_module(f"{package.__name__}.{info.name}")
            definition = getattr(imported, "MODULE_DEFINITION", None)
            if definition is None:
                continue
            if not isinstance(definition, ModuleDefinition):
                raise TypeError(
                    f"{imported.__name__}.MODULE_DEFINITION deve ser ModuleDefinition."
                )
            if definition.manifest.key != info.name:
                raise ValueError(
                    f"Modulo '{definition.manifest.key}' deve usar uma pasta com a mesma chave."
                )
            if self.get(definition.manifest.key) is definition:
                continue
            if self.get(definition.manifest.key) is not None:
                raise ValueError(f"Modulo duplicado: {definition.manifest.key}.")
            self._validate_local_keys(definition)
            discovered.append(definition)
        self.register_many(discovered)

    def validate_dependencies(self) -> None:
        for definition in self._definitions.values():
            for dependency in definition.manifest.dependencies:
                target = self._definitions.get(dependency.module_key)
                if target is None:
                    if dependency.optional:
                        continue
                    raise ValueError(
                        f"Modulo '{definition.manifest.key}' depende de "
                        f"'{dependency.module_key}', que nao esta registrado."
                    )
                if target.manifest.contract_version < dependency.minimum_contract_version:
                    raise ValueError(
                        f"Modulo '{dependency.module_key}' possui contrato incompatível."
                    )

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(key: str) -> None:
            if key in visiting:
                raise ValueError(f"Ciclo de dependencias detectado em '{key}'.")
            if key in visited:
                return
            visiting.add(key)
            definition = self._definitions[key]
            for dependency in definition.manifest.dependencies:
                if dependency.module_key in self._definitions:
                    visit(dependency.module_key)
            visiting.remove(key)
            visited.add(key)

        for key in self._definitions:
            visit(key)

    @staticmethod
    def _validate_local_keys(definition: ModuleDefinition) -> None:
        module_key = definition.manifest.key
        if definition.manifest.default_runtime_mode not in definition.manifest.runtime_modes:
            raise ValueError(
                f"Runtime padrao de '{module_key}' nao esta entre os modos suportados."
            )
        groups = {
            "capability": [item.key for item in definition.capabilities],
            "panel": [item.key for item in definition.panels],
            "action": [item.key for item in definition.actions],
            "job": [item.key for item in definition.jobs],
            "notification": [item.key for item in definition.notifications],
        }
        for kind, keys in groups.items():
            if len(keys) != len(set(keys)):
                raise ValueError(f"{kind} duplicado no modulo '{module_key}'.")
        capabilities = set(groups["capability"])
        panels = set(groups["panel"])
        for action in definition.actions:
            if action.capability not in capabilities:
                raise ValueError(
                    f"Acao '{action.key}' referencia capability inexistente '{action.capability}'."
                )
            if action.panel_key and action.panel_key not in panels:
                raise ValueError(
                    f"Acao '{action.key}' referencia painel inexistente '{action.panel_key}'."
                )


module_registry = ModuleRegistry()


def discover_domain_modules() -> ModuleRegistry:
    from app import domain_modules

    module_registry.discover(domain_modules)
    return module_registry
