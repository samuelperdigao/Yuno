"""Testes da reconciliacao de estrutura e do diagnostico.

O comportamento que estes testes protegem e comercial, nao tecnico: o cliente
vai renomear canal, mover canal de categoria e rodar `/yuno configurar` de novo
quando algo parecer errado. Nenhuma dessas acoes pode duplicar canal nem desfazer
a organizacao dele.
"""

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import discord
import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "bot"))

from yuno_bot import diagnostics, server_setup  # noqa: E402


# ── Dublês ────────────────────────────────────────────────────────────────────


def _texto(canal_id: int, nome: str, category_id: int | None = None):
    canal = MagicMock(spec=discord.TextChannel)
    canal.id = canal_id
    canal.name = nome
    canal.category_id = category_id
    canal.mention = f"<#{canal_id}>"
    return canal


class FakeGuild:
    """Servidor de mentira com o minimo que server_setup usa."""

    def __init__(self, categorias=(), canais=()):
        self.name = "Servidor Teste"
        self.id = 1
        self.categories = []
        self.text_channels = list(canais)
        self._seq = 9000
        self.me = None
        for cat_id, nome in categorias:
            self._nova_categoria(cat_id, nome)

    def _novo_id(self) -> int:
        self._seq += 1
        return self._seq

    def _nova_categoria(self, cat_id: int, nome: str):
        categoria = MagicMock(spec=discord.CategoryChannel)
        categoria.id = cat_id
        categoria.name = nome

        async def create_text_channel(name, reason=None, _cat=categoria):
            canal = _texto(self._novo_id(), name, _cat.id)
            self.text_channels.append(canal)
            return canal

        categoria.create_text_channel = create_text_channel
        self.categories.append(categoria)
        return categoria

    def get_channel(self, channel_id: int):
        for canal in (*self.categories, *self.text_channels):
            if canal.id == channel_id:
                return canal
        return None

    async def create_category(self, name, reason=None):
        return self._nova_categoria(self._novo_id(), name)


def _config_de(guild: FakeGuild, resultado) -> dict:
    return server_setup.build_setup_config(
        current_config={},
        guild=guild,
        categories=resultado.categories,
        channels=resultado.channels,
    )


# ── Reconciliacao ─────────────────────────────────────────────────────────────


def test_servidor_vazio_cria_tudo():
    guild = FakeGuild()
    resultado = asyncio.run(server_setup.ensure_setup_channels(guild, {}))

    assert len(resultado.categories) == len(server_setup.SETUP_CATEGORIES)
    esperado = len(server_setup.setup_channels()) + len(server_setup.log_channels())
    assert len(resultado.channels) == esperado
    assert not resultado.reused


def test_rodar_duas_vezes_nao_duplica_nada():
    """A prova de idempotencia: a segunda passada nao cria nem adota nada."""
    guild = FakeGuild()
    primeira = asyncio.run(server_setup.ensure_setup_channels(guild, {}))
    config = _config_de(guild, primeira)

    canais_apos_primeira = len(guild.text_channels)
    segunda = asyncio.run(server_setup.ensure_setup_channels(guild, config))

    assert segunda.created == []
    assert segunda.adopted == []
    assert len(guild.text_channels) == canais_apos_primeira
    assert len(segunda.reused) == len(segunda.categories) + len(segunda.channels)


def test_canal_renomeado_pelo_cliente_continua_sendo_o_mesmo():
    """Era o bug: o bot achava por nome, nao achava, e criava um duplicado."""
    guild = FakeGuild()
    primeira = asyncio.run(server_setup.ensure_setup_channels(guild, {}))
    config = _config_de(guild, primeira)

    painel = primeira.channels["painel"]
    painel.name = "central-da-familia"
    total_antes = len(guild.text_channels)

    segunda = asyncio.run(server_setup.ensure_setup_channels(guild, config))

    assert segunda.channels["painel"].id == painel.id
    assert len(guild.text_channels) == total_antes, "criou canal duplicado apos rename"


def test_canal_movido_de_categoria_nao_e_movido_de_volta():
    """Se o cliente organizou o servidor dele, o bot nao desfaz."""
    guild = FakeGuild()
    primeira = asyncio.run(server_setup.ensure_setup_channels(guild, {}))
    config = _config_de(guild, primeira)

    painel = primeira.channels["painel"]
    painel.category_id = 123456  # cliente arrastou para outra categoria

    asyncio.run(server_setup.ensure_setup_channels(guild, config))

    painel.edit.assert_not_called()
    assert painel.category_id == 123456


def test_adota_canal_de_mesmo_nome_quando_nao_ha_id_salvo():
    """Servidor configurado antes desta versao migra sem duplicar nada."""
    existente = _texto(555, "yuno-painel")
    guild = FakeGuild(canais=[existente])

    resultado = asyncio.run(server_setup.ensure_setup_channels(guild, {}))

    assert resultado.channels["painel"].id == 555
    assert "#yuno-painel" in resultado.adopted


def test_canal_apagado_pelo_cliente_e_recriado():
    guild = FakeGuild()
    primeira = asyncio.run(server_setup.ensure_setup_channels(guild, {}))
    config = _config_de(guild, primeira)

    painel = primeira.channels["painel"]
    guild.text_channels.remove(painel)

    segunda = asyncio.run(server_setup.ensure_setup_channels(guild, config))

    assert segunda.channels["painel"].id != painel.id
    assert "#yuno-painel" in segunda.created


def test_modulo_desligado_pelo_cliente_permanece_desligado():
    """Atualizacao do Yuno nao pode reativar modulo que o cliente desligou."""
    guild = FakeGuild()
    resultado = asyncio.run(server_setup.ensure_setup_channels(guild, {}))

    config = server_setup.build_setup_config(
        current_config={"modules": {"radio": False}},
        guild=guild,
        categories=resultado.categories,
        channels=resultado.channels,
    )

    assert config["modules"]["radio"] is False
    assert config["modules"]["set"] is True


# ── Diagnostico ───────────────────────────────────────────────────────────────


def _membro(**permissoes):
    membro = MagicMock()
    perms = MagicMock()
    perms.administrator = permissoes.pop("administrator", False)
    for nome, _ in server_setup.PERMISSOES_NECESSARIAS:
        setattr(perms, nome, permissoes.get(nome, True))
    membro.guild_permissions = perms
    return membro


def _guild_configurado():
    guild = FakeGuild()
    resultado = asyncio.run(server_setup.ensure_setup_channels(guild, {}))
    guild.me = _membro()
    return guild, _config_de(guild, resultado)


def test_diagnostico_de_servidor_pronto():
    guild, config = _guild_configurado()
    relatorio = diagnostics.diagnose(guild, config, licenca_ativa=True)

    assert relatorio.pronto
    assert relatorio.pendencias == ()


def test_diagnostico_sem_licenca_nunca_esta_pronto():
    guild, config = _guild_configurado()
    relatorio = diagnostics.diagnose(guild, config, licenca_ativa=False)

    assert not relatorio.pronto
    embed = diagnostics.diagnostic_embed(relatorio, guild.name)
    assert "licenca" in embed.title.lower()


def test_diagnostico_aponta_canal_apagado():
    guild, config = _guild_configurado()
    apagado = guild.get_channel(int(config["settings"]["discord_setup"]["channel_ids"]["painel"]))
    guild.text_channels.remove(apagado)

    relatorio = diagnostics.diagnose(guild, config, licenca_ativa=True)

    assert not relatorio.pronto
    assert any("apagado" in item.detalhe for item in relatorio.pendencias)


def test_diagnostico_aponta_permissao_faltando():
    guild, config = _guild_configurado()
    guild.me = _membro(manage_channels=False)

    relatorio = diagnostics.diagnose(guild, config, licenca_ativa=True)

    faltando = [item.nome for item in relatorio.pendencias]
    assert "manage_channels" in faltando


def test_administrador_dispensa_checagem_individual():
    guild, config = _guild_configurado()
    guild.me = _membro(administrator=True, manage_channels=False)

    relatorio = diagnostics.diagnose(guild, config, licenca_ativa=True)

    assert relatorio.pronto


def test_embed_respeita_limite_de_campo_do_discord():
    """Servidor sem nada configurado gera muitas pendencias; o embed nao pode estourar."""
    guild = FakeGuild()
    guild.me = _membro()
    relatorio = diagnostics.diagnose(guild, {}, licenca_ativa=True)
    embed = diagnostics.diagnostic_embed(relatorio, guild.name)

    for campo in embed.fields:
        assert len(campo.value) <= 1024, f"campo '{campo.name}' estourou o limite do Discord"
