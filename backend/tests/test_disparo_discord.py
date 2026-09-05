"""Testes das funcoes puras do modulo `disparo`.

Sem um mapeamento formal "membro -> canal privado" no Yuno hoje (ver
`bot/yuno_bot/commands/disparo/helpers.py`), a selecao de canais-alvo depende
de uma categoria configuravel mais uma lista de exclusao. Estes testes travam
essa selecao e os embeds do painel/log sem precisar de um bot ou API reais.
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "bot"))

import discord  # noqa: E402

from yuno_bot.commands.disparo import MODULE  # noqa: E402
from yuno_bot.commands.disparo.embeds import (  # noqa: E402
    log_envio_embed,
    log_exclusao_embed,
    painel_disparo_embed,
)
from yuno_bot.commands.disparo.helpers import (  # noqa: E402
    parse_excluded_ids,
    valid_target_channels,
)


def _canal(channel_id: int, nome: str) -> discord.TextChannel:
    canal = MagicMock(spec=discord.TextChannel)
    canal.id = channel_id
    canal.name = nome
    return canal


def _categoria(*canais: discord.TextChannel) -> discord.CategoryChannel:
    categoria = MagicMock(spec=discord.CategoryChannel)
    categoria.text_channels = list(canais)
    return categoria


# ── parse_excluded_ids ───────────────────────────────────────────────────────


def test_parse_excluded_ids_retorna_lista_vazia_sem_entrada():
    assert parse_excluded_ids(None) == []
    assert parse_excluded_ids("") == []
    assert parse_excluded_ids("   ") == []


def test_parse_excluded_ids_aceita_ids_crus_separados_por_virgula():
    assert parse_excluded_ids("111, 222,333") == ["111", "222", "333"]


def test_parse_excluded_ids_extrai_digitos_de_mencoes_de_canal():
    assert parse_excluded_ids("<#111>, <#222>") == ["111", "222"]


def test_parse_excluded_ids_aceita_quebras_de_linha_e_remove_duplicatas():
    assert parse_excluded_ids("111\n222,111") == ["111", "222"]


# ── valid_target_channels ────────────────────────────────────────────────────


def test_valid_target_channels_retorna_todos_canais_sem_exclusao():
    categoria = _categoria(_canal(1, "joao"), _canal(2, "maria"))
    assert [c.id for c in valid_target_channels(categoria)] == [1, 2]


def test_valid_target_channels_pula_canais_da_lista_de_exclusao():
    categoria = _categoria(_canal(1, "joao"), _canal(2, "avisos"))
    resultado = valid_target_channels(categoria, excluded_ids=["2"])
    assert [c.id for c in resultado] == [1]


def test_valid_target_channels_pula_pastas_livres_sem_dono():
    categoria = _categoria(_canal(1, "joao"), _canal(2, "livre-01"), _canal(3, "LIVRE-02"))
    resultado = valid_target_channels(categoria)
    assert [c.id for c in resultado] == [1]


# ── embeds ────────────────────────────────────────────────────────────────────


def test_painel_disparo_embed_descreve_o_painel():
    embed = painel_disparo_embed()
    assert "Disparo" in embed.title
    assert any("categoria configurada" in field.value for field in embed.fields)


def test_log_envio_embed_traz_autor_categoria_e_resultado():
    autor = SimpleNamespace(mention="<@1>", id=1)
    embed = log_envio_embed(autor=autor, enviados=3, total=5, categoria="Pastas")
    valores = {field.name: field.value for field in embed.fields}
    assert "3 de 5 canal(is)" in valores["Resultado"]
    assert valores["Categoria"] == "Pastas"


def test_log_exclusao_embed_traz_contagem_de_deletados_e_falhas():
    autor = SimpleNamespace(mention="<@1>", id=1)
    embed = log_exclusao_embed(autor=autor, deletados=4, falhas=1)
    valores = {field.name: field.value for field in embed.fields}
    assert "4 apagada(s), 1 falha(s)" in valores["Resultado"]


# ── ModuleSpec ────────────────────────────────────────────────────────────────


def test_module_spec_sai_do_catalogo_aposentado_com_configuracao_propria():
    assert MODULE.retired is False
    assert len(MODULE.cogs) == 1
    assert len(MODULE.views) == 1
    assert MODULE.log_channel == "disparo-logs"
    assert {field.key for field in MODULE.dashboard_fields} == {
        "target_category_id",
        "excluded_channel_ids",
    }
