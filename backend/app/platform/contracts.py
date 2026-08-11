from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
try:
    from enum import StrEnum
except ImportError:  # Python 3.10 do servidor de teste
    from enum import Enum

    class StrEnum(str, Enum):
        pass
import re
from typing import Any, Awaitable, Callable, Protocol
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ConfigurationFieldType(StrEnum):
    text = "text"
    number = "number"
    decimal = "decimal"
    boolean = "boolean"
    channel = "channel"
    category = "category"
    role = "role"
    roles = "roles"
    color = "color"
    url = "url"
    enum = "enum"
    duration = "duration"
    date = "date"
    time = "time"
    timezone = "timezone"
    collection = "collection"
    resource = "resource"


@dataclass(frozen=True)
class ConfigurationField:
    key: str
    label: str
    field_type: ConfigurationFieldType
    required: bool = False
    default: Any = None
    description: str = ""
    constraints: dict[str, Any] = field(default_factory=dict)
    sensitive: bool = False
    presentation: dict[str, Any] = field(default_factory=dict)


ConfigValidator = Callable[[dict[str, Any]], list[str]]


@dataclass(frozen=True)
class ConfigurationContract:
    schema_version: int
    fields: tuple[ConfigurationField, ...] = ()
    validators: tuple[ConfigValidator, ...] = ()

    def defaults(self) -> dict[str, Any]:
        return {
            item.key: item.default
            for item in self.fields
            if item.default is not None
        }

    def validate(self, data: dict[str, Any]) -> list[str]:
        allowed = {item.key for item in self.fields}
        errors = [f"Campo desconhecido: {key}." for key in data if key not in allowed]
        for item in self.fields:
            if item.required and data.get(item.key) is None:
                errors.append(f"Campo obrigatorio: {item.key}.")
                continue
            if item.key not in data or data[item.key] is None:
                continue
            errors.extend(_validate_field(item, data[item.key]))
        for validator in self.validators:
            errors.extend(validator(data))
        return errors


def _validate_field(field: ConfigurationField, value: Any) -> list[str]:
    kind = field.field_type
    errors: list[str] = []
    string_types = {
        ConfigurationFieldType.text,
        ConfigurationFieldType.channel,
        ConfigurationFieldType.category,
        ConfigurationFieldType.role,
        ConfigurationFieldType.color,
        ConfigurationFieldType.url,
        ConfigurationFieldType.enum,
        ConfigurationFieldType.date,
        ConfigurationFieldType.time,
        ConfigurationFieldType.timezone,
        ConfigurationFieldType.resource,
    }
    if kind in string_types and not isinstance(value, str):
        return [f"{field.key} deve ser texto."]
    if kind == ConfigurationFieldType.number and (
        not isinstance(value, int) or isinstance(value, bool)
    ):
        return [f"{field.key} deve ser numero inteiro."]
    if kind == ConfigurationFieldType.decimal and (
        not isinstance(value, (int, float, Decimal)) or isinstance(value, bool)
    ):
        return [f"{field.key} deve ser decimal."]
    if kind == ConfigurationFieldType.boolean and not isinstance(value, bool):
        return [f"{field.key} deve ser booleano."]
    if kind == ConfigurationFieldType.roles and (
        not isinstance(value, list) or not all(isinstance(item, str) for item in value)
    ):
        return [f"{field.key} deve ser uma lista de cargos."]
    if kind == ConfigurationFieldType.collection and not isinstance(value, list):
        return [f"{field.key} deve ser uma colecao."]
    if kind == ConfigurationFieldType.duration and (
        not isinstance(value, (int, str)) or isinstance(value, bool)
    ):
        return [f"{field.key} deve ser duracao em segundos ou ISO-8601."]
    if kind == ConfigurationFieldType.color and not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        errors.append(f"{field.key} deve usar o formato #RRGGBB.")
    if kind == ConfigurationFieldType.url:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            errors.append(f"{field.key} deve ser URL HTTP(S) valida.")
    if kind == ConfigurationFieldType.timezone:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            errors.append(f"{field.key} deve ser timezone IANA valido.")
    constraints = field.constraints
    if "choices" in constraints and value not in constraints["choices"]:
        errors.append(f"{field.key} deve ser uma das opcoes permitidas.")
    if isinstance(value, (str, list)):
        if "min_length" in constraints and len(value) < int(constraints["min_length"]):
            errors.append(f"{field.key} e menor que o minimo permitido.")
        if "max_length" in constraints and len(value) > int(constraints["max_length"]):
            errors.append(f"{field.key} excede o limite permitido.")
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        if "min" in constraints and value < constraints["min"]:
            errors.append(f"{field.key} e menor que o minimo permitido.")
        if "max" in constraints and value > constraints["max"]:
            errors.append(f"{field.key} excede o maximo permitido.")
    return errors


@dataclass(frozen=True)
class ModuleDependency:
    module_key: str
    minimum_contract_version: int = 1
    optional: bool = False


@dataclass(frozen=True)
class ModuleManifest:
    key: str
    name: str
    description: str
    contract_version: int = 1
    domain_version: str = "legacy"
    minimum_plan: str = "basico"
    dependencies: tuple[ModuleDependency, ...] = ()
    required_discord_permissions: tuple[str, ...] = ()
    provided_resources: tuple[str, ...] = ()
    runtime_modes: tuple[str, ...] = ("legacy",)
    default_runtime_mode: str = "legacy"


@dataclass(frozen=True)
class CapabilityDefinition:
    key: str
    administrative: bool = False
    resource_scoped: bool = False
    allow_resource_owner: bool = False
    allow_automation: bool = False
    admin_bypass: bool = False
    denial_reason: str = "Voce nao possui permissao para esta acao."


@dataclass(frozen=True)
class LifecyclePolicy:
    requires_published_configuration: bool = False
    may_pause: bool = True
    may_deactivate: bool = True


@dataclass(frozen=True)
class PanelContract:
    key: str
    durable: bool = True
    instance_type: str = "singleton"
    recovery_policy: str = "manual"


@dataclass(frozen=True)
class ActionContract:
    key: str
    capability: str
    panel_key: str | None = None


@dataclass(frozen=True)
class JobDefinition:
    key: str
    timeout_seconds: int = 60
    max_attempts: int = 5
    allow_late: bool = True


@dataclass(frozen=True)
class NotificationDefinition:
    key: str
    destination_types: tuple[str, ...] = ("channel",)


class HealthContributor(Protocol):
    key: str

    async def __call__(self, session: Any, guild_id: str) -> list[dict[str, Any]]: ...


class MigrationContract(Protocol):
    key: str

    async def inventory(self, session: Any, guild_id: str) -> dict[str, Any]: ...

    async def validate(self, session: Any, guild_id: str) -> list[str]: ...


@dataclass(frozen=True)
class ModuleDefinition:
    manifest: ModuleManifest
    configuration: ConfigurationContract | None = None
    capabilities: tuple[CapabilityDefinition, ...] = ()
    lifecycle: LifecyclePolicy = field(default_factory=LifecyclePolicy)
    panels: tuple[PanelContract, ...] = ()
    actions: tuple[ActionContract, ...] = ()
    jobs: tuple[JobDefinition, ...] = ()
    notifications: tuple[NotificationDefinition, ...] = ()
    health_checks: tuple[HealthContributor, ...] = ()
    migration: MigrationContract | None = None

    def capability(self, key: str) -> CapabilityDefinition | None:
        return next((item for item in self.capabilities if item.key == key), None)

    def panel(self, key: str) -> PanelContract | None:
        return next((item for item in self.panels if item.key == key), None)

    def job(self, key: str) -> JobDefinition | None:
        return next((item for item in self.jobs if item.key == key), None)

    def notification(self, key: str) -> NotificationDefinition | None:
        return next((item for item in self.notifications if item.key == key), None)
