import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "bot"))

from app.domain_modules.bau.domain import (  # noqa: E402
    DEFAULT_CATALOG,
    BauDomainError,
    apply_delta,
    clamp_page,
    normalize_name,
    page_count,
    parse_delta,
)
from app.domain_modules.bau.schemas import BauConfig  # noqa: E402
from yuno_bot.domain_modules.bau.renderers import BauLogData, BauRenderer  # noqa: E402
from yuno_bot.domain_modules.bau.ui import render_stock  # noqa: E402


def test_normalize_name_trims_and_rejects_empty() -> None:
    assert normalize_name("  Ferro  ", max_length=80) == "Ferro"
    with pytest.raises(BauDomainError, match="vazio"):
        normalize_name("   ", max_length=80)


def test_normalize_name_enforces_max_length() -> None:
    with pytest.raises(BauDomainError, match="máximo"):
        normalize_name("a" * 81, max_length=80)
    assert normalize_name("a" * 80, max_length=80) == "a" * 80


def test_parse_delta_blank_means_no_change() -> None:
    assert parse_delta("") is None
    assert parse_delta("   ") is None
    assert parse_delta("0") is None


def test_parse_delta_accepts_signed_integers() -> None:
    assert parse_delta("10") == 10
    assert parse_delta("+10") == 10
    assert parse_delta("-5") == -5


def test_parse_delta_rejects_non_numeric() -> None:
    with pytest.raises(BauDomainError, match="Valor inválido"):
        parse_delta("dez")
    with pytest.raises(BauDomainError, match="Valor inválido"):
        parse_delta("5.5")


def test_apply_delta_rejects_negative_result() -> None:
    with pytest.raises(BauDomainError, match="Estoque insuficiente"):
        apply_delta(3, -5, item_name="Ferro")


def test_apply_delta_rejects_above_max() -> None:
    with pytest.raises(BauDomainError, match="limite"):
        apply_delta(999_999, 100, item_name="Ferro")


def test_apply_delta_computes_new_quantity() -> None:
    assert apply_delta(10, 5, item_name="Ferro") == 15
    assert apply_delta(10, -5, item_name="Ferro") == 5
    assert apply_delta(0, 0, item_name="Ferro") == 0


def test_page_count_and_clamp_page() -> None:
    assert page_count(0) == 1
    assert page_count(5, page_size=5) == 1
    assert page_count(6, page_size=5) == 2
    assert clamp_page(5, total_items=6, page_size=5) == 1
    assert clamp_page(-1, total_items=6, page_size=5) == 0


def test_default_catalog_has_reasonable_shape() -> None:
    assert len(DEFAULT_CATALOG) >= 10
    total_items = sum(len(items) for _, items in DEFAULT_CATALOG)
    assert total_items >= 50
    names = [name for _, items in DEFAULT_CATALOG for name in items]
    assert len(names) == len(set(names)), "catálogo padrão não deve ter itens duplicados"


def test_bau_config_defaults() -> None:
    config = BauConfig()
    assert config.enabled is True
    assert config.panel_channel_id == ""
    assert config.staff_role_ids == []
    with pytest.raises(Exception):
        BauConfig.model_validate({"unknown": True})


def test_bau_renderer_movement_log() -> None:
    data = BauLogData.from_payload(
        {
            "operation": "movimentacao",
            "actor_id": "10",
            "changes": [
                {"item_name": "Ferro", "delta": 10, "before": 5, "after": 15},
                {"item_name": "Aço", "delta": -3, "before": 8, "after": 5},
            ],
        }
    )
    embed = BauRenderer().render_log(data)
    field_values = "\n".join(str(field.value) for field in embed.fields)
    assert "Ferro" in field_values
    assert "+10" in field_values
    assert "-3" in field_values


def test_bau_renderer_clear_log() -> None:
    data = BauLogData.from_payload({"operation": "limpeza", "actor_id": "10", "items_reset": 42})
    embed = BauRenderer().render_log(data)
    assert "zerado" in str(embed.description)
    assert any("42" in str(field.value) for field in embed.fields)


def test_render_stock_lists_categories_and_select() -> None:
    config = BauConfig().model_dump(mode="json")
    summary = [{"id": "cat-1", "name": "Materiais", "item_count": 3, "total_quantity": 42}]
    result = asyncio.run(render_stock({"config": config, "summary": summary})).data
    text = str(result)
    assert "yuno:v1:bau:stock:select_category" in text
    assert "Materiais" in text
    assert "42" in text


def test_render_stock_handles_empty_catalog() -> None:
    config = BauConfig().model_dump(mode="json")
    result = asyncio.run(render_stock({"config": config, "summary": []})).data
    text = str(result)
    assert "Catálogo vazio" in text
