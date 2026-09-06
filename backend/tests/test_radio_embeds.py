"""Testes das funcoes puras do modulo de Radio.

`embeds.py` nao faz I/O nem depende de `discord.Interaction`, entao esses
testes rodam sem mock de rede nem gateway.
"""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "bot"))

from yuno_bot.commands.radio.embeds import (  # noqa: E402
    channel_name_for,
    normalize_frequencia,
    panel_embed,
    radio_announcement_embed,
    radio_panel_message_id,
    with_radio_panel_message_id,
)


class FakeUser:
    def __init__(self, display_name: str) -> None:
        self.display_name = display_name


def test_normalize_frequencia_aceita_numero_simples():
    assert normalize_frequencia("1221") == "1221"


def test_normalize_frequencia_remove_espacos_nas_pontas():
    assert normalize_frequencia("  1221  ") == "1221"


def test_normalize_frequencia_colapsa_espacos_internos():
    assert normalize_frequencia("12  21") == "12 21"


def test_normalize_frequencia_remove_caracteres_perigosos():
    assert normalize_frequencia("12`21@everyone#") == "1221everyone"


def test_normalize_frequencia_rejeita_vazio():
    with pytest.raises(ValueError):
        normalize_frequencia("")


def test_normalize_frequencia_rejeita_so_espacos():
    with pytest.raises(ValueError):
        normalize_frequencia("   ")


def test_normalize_frequencia_rejeita_texto_longo_demais():
    with pytest.raises(ValueError):
        normalize_frequencia("1" * 21)


def test_normalize_frequencia_aceita_ate_o_limite():
    assert normalize_frequencia("1" * 20) == "1" * 20


def test_channel_name_for_numero_simples():
    assert channel_name_for("1221") == "┃📻-radio-1221!"


def test_channel_name_for_normaliza_maiusculas_e_espacos():
    assert channel_name_for("FM 102 9") == "┃📻-radio-fm-102-9!"


def test_channel_name_for_colapsa_hifens_repetidos():
    assert channel_name_for("--105--") == "┃📻-radio-105!"


def test_radio_panel_message_id_ausente_retorna_none():
    assert radio_panel_message_id({}) is None


def test_radio_panel_message_id_le_valor_salvo():
    config = {"settings": {"radio": {"panel_message_id": "123456"}}}
    assert radio_panel_message_id(config) == 123456


def test_radio_panel_message_id_ignora_valor_invalido():
    config = {"settings": {"radio": {"panel_message_id": "nao-e-um-id"}}}
    assert radio_panel_message_id(config) is None


def test_with_radio_panel_message_id_preserva_o_resto_da_configuracao():
    current = {
        "guild_name": "Servidor",
        "admin_role_ids": ["1"],
        "log_channel_id": "9",
        "modules": {"radio": True},
        "command_permissions": {"outro.comando": {"role_ids": ["7"]}},
        "messages": {"boas_vindas": "oi"},
        "settings": {"outro_modulo": {"chave": "valor"}},
    }

    updated = with_radio_panel_message_id(current, message_id=999)

    assert updated["guild_name"] == "Servidor"
    assert updated["admin_role_ids"] == ["1"]
    assert updated["command_permissions"] == {"outro.comando": {"role_ids": ["7"]}}
    assert updated["settings"]["outro_modulo"] == {"chave": "valor"}
    assert updated["settings"]["radio"] == {"panel_message_id": "999"}


def test_with_radio_panel_message_id_mantem_outras_chaves_do_settings_radio():
    current = {"settings": {"radio": {"algo_futuro": "valor"}}}
    updated = with_radio_panel_message_id(current, message_id=42)
    assert updated["settings"]["radio"] == {"algo_futuro": "valor", "panel_message_id": "42"}


def test_panel_embed_tem_titulo_e_descricao():
    embed = panel_embed()
    assert "Rádio" in embed.title
    assert embed.description


def test_radio_announcement_embed_menciona_a_frequencia_e_o_autor():
    embed = radio_announcement_embed("1221", FakeUser("Zeca"))
    assert "1221" in embed.description
    assert "Zeca" in embed.footer.text
