"""Diagnostico do estado do Yuno num servidor.

Existe por uma razao comercial: a maior parte dos tickets de suporte de um bot
vendido e "nao esta funcionando", sem nenhuma informacao util junto. Um comando
que responde exatamente o que falta, em linguagem que o dono do servidor
entende, resolve o problema antes de ele virar mensagem no seu privado.

`diagnose` e uma funcao pura sobre a config e o estado do servidor — nao faz I/O
e por isso e testavel sem subir bot nenhum. O embed e so apresentacao.
"""

from __future__ import annotations

from dataclasses import dataclass

import discord

from yuno_bot import modules, server_setup
from yuno_bot.commands.shared import YUNO_GREEN, YUNO_ORANGE, YUNO_RED

LIMITE_CAMPO = 1000  # embed field aceita 1024; a folga cobre o sufixo de corte


@dataclass(frozen=True)
class Item:
    nome: str
    ok: bool
    detalhe: str = ""


@dataclass(frozen=True)
class Diagnostico:
    licenca_ativa: bool
    permissoes: tuple[Item, ...]
    estrutura: tuple[Item, ...]
    modulos: tuple[Item, ...]

    @property
    def pendencias(self) -> tuple[Item, ...]:
        return tuple(
            item for grupo in (self.permissoes, self.estrutura) for item in grupo if not item.ok
        )

    @property
    def pronto(self) -> bool:
        return self.licenca_ativa and not self.pendencias


def _permissoes(guild: discord.Guild) -> tuple[Item, ...]:
    membro = guild.me
    if membro is None:
        return (Item("Permissoes do bot", False, "nao consegui ler minhas proprias permissoes"),)

    perms = membro.guild_permissions
    if perms.administrator:
        return (Item("Permissoes do bot", True, "administrador"),)

    return tuple(
        Item(nome, getattr(perms, nome, False), motivo)
        for nome, motivo in server_setup.PERMISSOES_NECESSARIAS
    )


def _estrutura(guild: discord.Guild, config: dict) -> tuple[Item, ...]:
    itens: list[Item] = []

    for spec in server_setup.setup_channels():
        canal_id = server_setup.saved_channel_id(config, spec.key)
        canal = guild.get_channel(canal_id) if canal_id else None
        if canal is None:
            itens.append(
                Item(
                    f"#{spec.name}",
                    False,
                    "nao configurado" if not canal_id else "o canal salvo foi apagado",
                )
            )
        else:
            itens.append(Item(canal.mention, True))

    for module_key, nome in server_setup.log_channels().items():
        canal_id = server_setup.saved_log_channel_id(config, module_key)
        canal = guild.get_channel(canal_id) if canal_id else None
        if canal is None:
            itens.append(
                Item(
                    f"#{nome}",
                    False,
                    "log nao configurado" if not canal_id else "o canal de log salvo foi apagado",
                )
            )
        else:
            itens.append(Item(canal.mention, True))

    return tuple(itens)


def _modulos(config: dict) -> tuple[Item, ...]:
    ligados = config.get("modules") or {}
    registry = modules.discover_modules()
    return tuple(
        Item(f"{spec.icon} {spec.nome}", bool(ligados.get(key, False)))
        for key, spec in registry.items()
    )


def diagnose(guild: discord.Guild, config: dict, *, licenca_ativa: bool) -> Diagnostico:
    return Diagnostico(
        licenca_ativa=licenca_ativa,
        permissoes=_permissoes(guild),
        estrutura=_estrutura(guild, config),
        modulos=_modulos(config),
    )


def _truncar(linhas: list[str], *, vazio: str) -> str:
    if not linhas:
        return vazio
    texto = ""
    for indice, linha in enumerate(linhas):
        if len(texto) + len(linha) + 1 > LIMITE_CAMPO:
            return f"{texto}...e mais {len(linhas) - indice}."
        texto += linha + "\n"
    return texto.rstrip()


def diagnostic_embed(diagnostico: Diagnostico, guild_name: str) -> discord.Embed:
    if not diagnostico.licenca_ativa:
        cor, titulo = YUNO_RED, "Yuno sem licenca ativa"
    elif diagnostico.pronto:
        cor, titulo = YUNO_GREEN, "Yuno configurado e pronto"
    else:
        cor, titulo = YUNO_ORANGE, "Yuno com pendencias de configuracao"

    embed = discord.Embed(title=titulo, color=cor, timestamp=discord.utils.utcnow())
    embed.set_footer(text=f"Diagnostico do Yuno em {guild_name}")

    embed.add_field(
        name="Licenca",
        value=(
            "Ativa neste servidor."
            if diagnostico.licenca_ativa
            else "Sem licenca ativa. Ative pelo painel do Yuno para liberar os comandos."
        ),
        inline=False,
    )

    faltando_perm = [item for item in diagnostico.permissoes if not item.ok]
    embed.add_field(
        name="Permissoes",
        value=_truncar(
            [f"Preciso de **{item.nome}** para {item.detalhe}." for item in faltando_perm],
            vazio="Tenho tudo que preciso.",
        ),
        inline=False,
    )

    faltando_estrutura = [item for item in diagnostico.estrutura if not item.ok]
    total = len(diagnostico.estrutura)
    embed.add_field(
        name=f"Canais ({total - len(faltando_estrutura)}/{total})",
        value=_truncar(
            [f"{item.nome} — {item.detalhe}" for item in faltando_estrutura],
            vazio="Estrutura completa.",
        ),
        inline=False,
    )

    desligados = [item.nome for item in diagnostico.modulos if not item.ok]
    embed.add_field(
        name="Modulos",
        value=_truncar(
            [f"Desligado: {nome}" for nome in desligados],
            vazio="Todos os modulos estao ligados.",
        ),
        inline=False,
    )

    if faltando_estrutura and diagnostico.licenca_ativa:
        embed.add_field(
            name="O que fazer agora",
            value="Rode `/yuno configurar` — ele cria o que falta e nao mexe no que ja esta certo.",
            inline=False,
        )

    return embed
