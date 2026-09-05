import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "bot"))

from app.domain_modules.anuncio.domain import (  # noqa: E402
    AnuncioDomainError,
    normalize_content,
    normalize_title,
)
from app.domain_modules.anuncio.schemas import AnuncioConfig  # noqa: E402
from yuno_bot.domain_modules.anuncio.domain import AnuncioUIError, parse_yes_no  # noqa: E402
from yuno_bot.domain_modules.anuncio.embeds import (  # noqa: E402
    AnuncioLogData,
    build_announcement_embed,
    build_log_embed,
)
from yuno_bot.domain_modules.anuncio.ui import render_public  # noqa: E402


def test_normalize_title_trims_and_rejects_empty() -> None:
    assert normalize_title("  Aviso importante  ") == "Aviso importante"
    with pytest.raises(AnuncioDomainError, match="vazio"):
        normalize_title("")
    with pytest.raises(AnuncioDomainError, match="vazio"):
        normalize_title("   ")


def test_normalize_title_enforces_max_length() -> None:
    with pytest.raises(AnuncioDomainError, match="256"):
        normalize_title("a" * 257)
    assert normalize_title("a" * 256) == "a" * 256


def test_normalize_content_trims_and_rejects_empty() -> None:
    assert normalize_content("  Servidor vai reiniciar às 20h  ") == "Servidor vai reiniciar às 20h"
    with pytest.raises(AnuncioDomainError, match="vazio"):
        normalize_content("")


def test_normalize_content_enforces_max_length() -> None:
    with pytest.raises(AnuncioDomainError, match="4000"):
        normalize_content("a" * 4001)
    assert normalize_content("a" * 4000) == "a" * 4000


def test_anuncio_config_defaults() -> None:
    config = AnuncioConfig()
    assert config.enabled is True
    assert config.channel_id == ""
    assert config.log_channel_id == ""
    assert config.authorized_role_ids == []
    with pytest.raises(Exception):
        AnuncioConfig.model_validate({"unknown": True})


@pytest.mark.parametrize(
    "text,expected",
    [
        ("sim", True),
        ("Sim", True),
        ("  SIM  ", True),
        ("s", True),
        ("yes", True),
        ("não", False),
        ("nao", False),
        ("Não", False),
        ("n", False),
        ("no", False),
    ],
)
def test_parse_yes_no_accepts_common_spellings(text: str, expected: bool) -> None:
    assert parse_yes_no(text) is expected


def test_parse_yes_no_rejects_unknown_text() -> None:
    with pytest.raises(AnuncioUIError):
        parse_yes_no("talvez")
    with pytest.raises(AnuncioUIError):
        parse_yes_no("")


def test_render_public_contains_button_and_title() -> None:
    config = AnuncioConfig().model_dump(mode="json")
    result = asyncio.run(render_public({"config": config})).data
    text = str(result)
    assert "yuno:v1:anuncio:public:open_form" in text
    assert config["button_label"] in text
    assert config["panel_title"] in text


def test_build_announcement_embed_uses_title_and_content() -> None:
    embed = build_announcement_embed(titulo="Manutenção agendada", conteudo="O servidor fica offline às 3h.")
    assert embed.title == "Manutenção agendada"
    assert embed.description == "O servidor fica offline às 3h."


def test_build_announcement_embed_clips_overflow() -> None:
    embed = build_announcement_embed(titulo="t" * 300, conteudo="c" * 5000)
    assert len(embed.title) == 256
    assert len(embed.description) == 4000


def test_build_log_embed_reports_metadata() -> None:
    data = AnuncioLogData(
        autor_id="10",
        titulo="Manutenção agendada",
        canal_id="20",
        mencionou_everyone=True,
        quantidade_arquivos=1,
        log_title="Novo anúncio publicado",
    )
    embed = build_log_embed(data)
    assert embed.title == "Novo anúncio publicado"
    field_values = {field.name: str(field.value) for field in embed.fields}
    assert field_values["👤 Publicado por"] == "<@10>"
    assert field_values["📍 Canal"] == "<#20>"
    assert field_values["📣 Mencionou @everyone"] == "Sim"
    assert field_values["📎 Arquivos anexados"] == "1"


def test_build_log_embed_defaults_without_mention_or_file() -> None:
    embed = build_log_embed(AnuncioLogData(titulo="Aviso"))
    field_values = {field.name: str(field.value) for field in embed.fields}
    assert field_values["📣 Mencionou @everyone"] == "Não"
    assert field_values["📎 Arquivos anexados"] == "0"
    assert field_values["👤 Publicado por"] == "—"
