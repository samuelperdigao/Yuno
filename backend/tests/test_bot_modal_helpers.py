import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bot"))

from yuno_bot.commands.encomenda.embeds import build_encomenda_payload
from yuno_bot.commands.meta.embeds import build_meta_payload
from yuno_bot.commands.parceria.embeds import build_parceria_payload
from yuno_bot.commands.producao.embeds import build_producao_payload
from yuno_bot.commands.set.embeds import build_set_panel_config, build_set_payload, panel_embed
from yuno_bot.commands.shared import log_channel_id_from_setup, parse_positive_int, send_module_log
from yuno_bot.server_setup import SETUP_LOG_CHANNELS, build_setup_config


def test_setup_config_includes_system_log_channels() -> None:
    categories = {
        "admin": SimpleNamespace(id=1),
        "operacao": SimpleNamespace(id=2),
        "logs": SimpleNamespace(id=3),
    }
    channels = {
        "logs": SimpleNamespace(id=10),
        "set_solicitar": SimpleNamespace(id=11),
        "set_aprovacao": SimpleNamespace(id=12),
        "metas": SimpleNamespace(id=13),
        "tickets": SimpleNamespace(id=14),
        "parcerias": SimpleNamespace(id=15),
        "encomendas": SimpleNamespace(id=16),
        "ausencias": SimpleNamespace(id=17),
        "radio": SimpleNamespace(id=18),
        "producao": SimpleNamespace(id=19),
        **{f"log_{module}": SimpleNamespace(id=100 + index) for index, module in enumerate(SETUP_LOG_CHANNELS)},
    }

    config = build_setup_config(
        current_config={"admin_role_ids": ["99"]},
        guild=SimpleNamespace(name="Guild Teste"),
        categories=categories,
        channels=channels,
    )

    setup = config["settings"]["discord_setup"]
    assert setup["category_ids"]["logs"] == "3"
    assert setup["channel_ids"]["set_aprovacao"] == "12"
    assert setup["log_channel_ids"]["set"] == "100"
    assert setup["log_channel_ids"]["producao"] == "107"


def test_modal_payload_builders() -> None:
    assert build_set_payload("Ana", "123") == {
        "nome": "Ana",
        "id_fivem": "123",
        "apelido_sugerido": "Ana | 123",
    }
    assert build_set_payload("A" * 40, "123") == {
        "nome": "A" * 32,
        "id_fivem": "123",
        "apelido_sugerido": f"{'A' * 32} | 123",
    }
    assert build_meta_payload("Colete", 10, "")["observacao"] == "Nao informado"
    assert build_producao_payload("Municao", 50, "turno noite")["quantidade"] == 50
    assert build_encomenda_payload("Item", 2, "amanha", "Familia", "")["valor_observacao"] == "Nao informado"
    assert build_parceria_payload("Fam", "Produto", "Contato", "", "")["contato_secundario"] == "Nao informado"


def test_set_panel_config_saves_channels_roles_and_message() -> None:
    config = build_set_panel_config(
        {
            "guild_name": "Cidade Setup",
            "admin_role_ids": ["admin-role"],
            "log_channel_id": "logs",
            "modules": {"set": True},
            "command_permissions": {
                "set.solicitar": {"category_ids": ["old-category"]},
                "set.aprovar": {"channel_ids": ["old-channel"]},
            },
            "messages": {"hello": "world"},
            "settings": {"discord_setup": {"channel_ids": {"metas": "metas-channel"}}},
        },
        panel_channel_id=11,
        approval_channel_id=12,
        approval_role_id=99,
        approved_role_id=100,
        panel_message_id=1234,
    )

    setup = config["settings"]["discord_setup"]
    assert setup["channel_ids"]["set_solicitar"] == "11"
    assert setup["channel_ids"]["set_aprovacao"] == "12"
    assert setup["channel_ids"]["metas"] == "metas-channel"
    assert config["command_permissions"]["set.solicitar"]["channel_ids"] == ["11"]
    assert config["command_permissions"]["set.solicitar"]["category_ids"] == ["old-category"]
    assert config["command_permissions"]["set.aprovar"]["channel_ids"] == ["12"]
    assert config["command_permissions"]["set.aprovar"]["role_ids"] == ["99"]
    assert config["command_permissions"]["set.reprovar"]["channel_ids"] == ["12"]
    assert config["command_permissions"]["set.reprovar"]["role_ids"] == ["99"]
    assert config["settings"]["set"]["approved_role_id"] == "100"
    assert config["settings"]["set"]["panel_message_id"] == "1234"


def test_set_panel_embed_copy_matches_requested_layout() -> None:
    embed = panel_embed("Cidade Setup")
    data = embed.to_dict()
    assert "Bem-vindo" not in data["title"]
    assert "Tempo medio" not in data["description"]
    assert "Tempo médio" not in data["description"]
    assert "Importante" in data["description"]
    assert "Pedir Set" in data["description"]


def test_parse_positive_int_rejects_invalid_values() -> None:
    assert parse_positive_int("1.250", "Quantidade") == 1250
    with pytest.raises(ValueError):
        parse_positive_int("abc", "Quantidade")
    with pytest.raises(ValueError):
        parse_positive_int("0", "Quantidade")


@pytest.mark.asyncio
async def test_send_module_log_returns_false_without_configured_channel() -> None:
    class FakeApi:
        async def get_guild_config(self, guild_id: int) -> dict:
            return {"settings": {"discord_setup": {"log_channel_ids": {}}}, "log_channel_id": None}

    interaction = SimpleNamespace(guild=SimpleNamespace(id=123))
    assert await send_module_log(FakeApi(), interaction, "set", SimpleNamespace()) is False
    assert log_channel_id_from_setup({"settings": {"discord_setup": {"log_channel_ids": {}}}}, "set") is None
