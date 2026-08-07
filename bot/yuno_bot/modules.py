"""Registry declarativo de modulos do Yuno.

Cada modulo em `yuno_bot/commands/<modulo>/__init__.py` expoe uma constante
`MODULE = ModuleSpec(...)` descrevendo tudo que o produto precisa saber sobre
ele: quais cogs registrar, quais views persistentes reativar no boot, quais
canais o setup deve criar e como ele aparece no dashboard de configuracao.

O motivo de existir: antes disso, a mesma lista de modulos vivia duplicada em
`main.py` (add_cog/add_view manuais), em `server_setup.py` (SETUP_CHANNELS,
SETUP_LOG_CHANNELS, MODULES) e no backend (`schemas.MODULES`). As copias sairam
de sincronia — `farm_tickets` existe no backend e nao existe no setup do bot.
Com o registry, essas listas passam a ser derivadas de uma fonte unica e um
modulo novo vira uma pasta, sem editar o core.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from types import ModuleType
from typing import TYPE_CHECKING, Callable, Iterator

import discord
from discord.ext import commands

if TYPE_CHECKING:
    from yuno_bot.control_plane import ControlPlaneSpec
    from yuno_bot.main import YunoBot


CogFactory = Callable[["ModuleContext"], commands.Cog]
ViewFactory = Callable[["ModuleContext"], discord.ui.View]

CATEGORIAS_VALIDAS = frozenset({"admin", "operacao", "logs"})
PLANOS_VALIDOS = frozenset({"basico", "pro", "premium"})


# ── Descritores ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SetupChannel:
    """Canal que `/yuno configurar` garante existir para este modulo.

    `command_keys` amarra o canal a comandos: o setup grava esses ids em
    `command_permissions`, restringindo o comando ao canal certo por padrao.
    """

    key: str
    name: str
    category: str
    command_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.category not in CATEGORIAS_VALIDAS:
            raise ValueError(
                f"SetupChannel '{self.key}': categoria '{self.category}' invalida. "
                f"Use uma de {sorted(CATEGORIAS_VALIDAS)}."
            )
        if self.name != self.name.lower() or " " in self.name:
            raise ValueError(f"SetupChannel '{self.key}': nome de canal deve ser minusculo e sem espacos.")


@dataclass(frozen=True)
class DashboardField:
    """Campo que o cliente preenche no dashboard de configuracao.

    O dashboard in-Discord e o painel web sao gerados a partir daqui, entao um
    modulo que declara seus campos corretamente aparece nos dois sem codigo
    adicional de UI.
    """

    key: str
    label: str
    tipo: str  # channel | category | role | roles | text | number
    obrigatorio: bool = True
    descricao: str = ""

    TIPOS = frozenset({"channel", "category", "role", "roles", "text", "number"})

    def __post_init__(self) -> None:
        if self.tipo not in DashboardField.TIPOS:
            raise ValueError(
                f"DashboardField '{self.key}': tipo '{self.tipo}' invalido. "
                f"Use um de {sorted(DashboardField.TIPOS)}."
            )


@dataclass(frozen=True)
class ModuleSpec:
    """Descricao completa de um modulo do Yuno.

    `cogs` e `views` recebem fabricas (nao classes) porque as dependencias
    variam: a maioria dos cogs so precisa do bot, `parceria` precisa tambem do
    repositorio, e as views de `farm_tickets` precisam da instancia do proprio
    cog. A fabrica recebe um `ModuleContext` e resolve isso sem que o loader
    conheca caso particular nenhum.
    """

    key: str
    nome: str
    descricao: str
    icon: str = "⚙️"
    ordem: int = 100
    plano_minimo: str = "basico"
    cogs: tuple[CogFactory, ...] = ()
    views: tuple[ViewFactory, ...] = ()
    setup_channels: tuple[SetupChannel, ...] = ()
    log_channel: str | None = None
    dashboard_fields: tuple[DashboardField, ...] = field(default_factory=tuple)
    control_plane: "ControlPlaneSpec | None" = None

    def __post_init__(self) -> None:
        if not self.key or self.key != self.key.lower().replace(" ", "_"):
            raise ValueError(f"ModuleSpec '{self.key}': key deve ser snake_case minusculo.")
        if self.plano_minimo not in PLANOS_VALIDOS:
            raise ValueError(
                f"ModuleSpec '{self.key}': plano '{self.plano_minimo}' invalido. "
                f"Use um de {sorted(PLANOS_VALIDOS)}."
            )

    @property
    def command_keys(self) -> tuple[str, ...]:
        return tuple(key for channel in self.setup_channels for key in channel.command_keys)


# ── Contexto de construcao ────────────────────────────────────────────────────


class ModuleContext:
    """Passado as fabricas durante o boot.

    Guarda os cogs ja instanciados para que uma view possa depender de um cog
    (caso do farm_tickets, cujas views delegam toda a logica ao cog). Por isso o
    loader instancia todos os cogs antes de qualquer view.
    """

    def __init__(self, bot: "YunoBot") -> None:
        self.bot = bot
        self._cogs: dict[type[commands.Cog], commands.Cog] = {}

    @property
    def api(self):
        return self.bot.api

    def remember(self, cog: commands.Cog) -> None:
        self._cogs[type(cog)] = cog

    def cog(self, cls: type[commands.Cog]) -> commands.Cog:
        try:
            return self._cogs[cls]
        except KeyError:
            raise LookupError(
                f"{cls.__name__} ainda nao foi instanciado. Views so podem depender de cogs; "
                f"verifique se o modulo que define {cls.__name__} esta declarado em cogs=()."
            ) from None


# ── Descoberta ────────────────────────────────────────────────────────────────


_registry: dict[str, ModuleSpec] | None = None


def _iter_specs(package: ModuleType) -> Iterator[ModuleSpec]:
    for info in pkgutil.iter_modules(package.__path__):
        if not info.ispkg:
            continue
        modulo = importlib.import_module(f"{package.__name__}.{info.name}")
        spec = getattr(modulo, "MODULE", None)
        if spec is None:
            continue
        if not isinstance(spec, ModuleSpec):
            raise TypeError(f"{package.__name__}.{info.name}.MODULE deve ser um ModuleSpec.")
        if spec.key != info.name:
            raise ValueError(
                f"{package.__name__}.{info.name}: MODULE.key e '{spec.key}' mas a pasta chama "
                f"'{info.name}'. Manter os dois iguais evita divergencia entre codigo e config."
            )
        yield spec


def _validate(specs: list[ModuleSpec]) -> None:
    """Falha no boot em vez de silenciosamente sobrescrever configuracao.

    Colisao de canal entre modulos e o tipo de bug que so aparece no servidor do
    cliente, depois da venda, e e caro de diagnosticar.
    """
    vistos_key: dict[str, str] = {}
    vistos_nome: dict[str, str] = {}
    for spec in specs:
        for canal in spec.setup_channels:
            if canal.key in vistos_key:
                raise ValueError(
                    f"Canal '{canal.key}' declarado por '{spec.key}' e por '{vistos_key[canal.key]}'."
                )
            if canal.name in vistos_nome:
                raise ValueError(
                    f"Canal #{canal.name} declarado por '{spec.key}' e por '{vistos_nome[canal.name]}'."
                )
            vistos_key[canal.key] = spec.key
            vistos_nome[canal.name] = spec.key
        if spec.log_channel:
            if spec.log_channel in vistos_nome:
                raise ValueError(
                    f"Canal de log #{spec.log_channel} de '{spec.key}' colide com "
                    f"'{vistos_nome[spec.log_channel]}'."
                )
            vistos_nome[spec.log_channel] = spec.key


def discover_modules(*, force: bool = False) -> dict[str, ModuleSpec]:
    """Importa `yuno_bot.commands.*` e devolve os specs ordenados."""
    global _registry
    if _registry is not None and not force:
        return _registry

    from yuno_bot import commands as commands_package

    specs = sorted(_iter_specs(commands_package), key=lambda s: (s.ordem, s.key))
    _validate(specs)
    _registry = {spec.key: spec for spec in specs}
    return _registry


def get_module(key: str) -> ModuleSpec | None:
    return discover_modules().get(key)


def module_keys() -> tuple[str, ...]:
    """Chaves na ordem canonica. Alimenta `modules` da GuildConfig."""
    return tuple(discover_modules())


def setup_channels() -> tuple[SetupChannel, ...]:
    return tuple(canal for spec in discover_modules().values() for canal in spec.setup_channels)


def log_channels() -> dict[str, str]:
    """`{chave_do_modulo: nome_do_canal_de_log}` para os modulos que tem log."""
    return {spec.key: spec.log_channel for spec in discover_modules().values() if spec.log_channel}


# ── Carga no boot ─────────────────────────────────────────────────────────────


async def load_modules(bot: "YunoBot") -> ModuleContext:
    """Instancia e registra todos os modulos descobertos.

    Ordem importa: cogs primeiro, views depois, porque view pode depender de cog.
    Falha de um modulo nao derruba os outros — num produto multi-tenant e melhor
    subir degradado e avisar do que deixar todos os clientes sem bot.
    """
    context = ModuleContext(bot)

    for spec in discover_modules().values():
        for fabrica in spec.cogs:
            try:
                cog = fabrica(context)
                await bot.add_cog(cog)
                context.remember(cog)
            except Exception:
                bot.log.exception("Falha ao registrar cog do modulo '%s'", spec.key)

    for spec in discover_modules().values():
        for fabrica in spec.views:
            try:
                bot.add_view(fabrica(context))
            except Exception:
                bot.log.exception("Falha ao registrar view do modulo '%s'", spec.key)

    return context
