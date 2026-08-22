from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bot"))

from yuno_bot.domain_modules.meta import MODULE_UI
from yuno_bot.domain_modules.meta import ui
from yuno_bot.platform.components_v2 import (
    meta_notice_payload,
    payload,
    send_meta_notice,
    text_display,
)


def _flatten_labels(component: dict) -> list[str]:
    result = []
    if component.get("label"):
        result.append(component["label"])
    for child in component.get("components") or []:
        result.extend(_flatten_labels(child))
    return result


def test_meta_adapter_exposes_only_stable_admin_actions_and_jobs() -> None:
    assert MODULE_UI.contract_version == 2
    assert MODULE_UI.panels == ()
    assert {item.key for item in MODULE_UI.jobs} == {
        "meta.goal.launch",
        "meta.cycle.transition",
        "meta.notice.reconcile",
        "meta.recovery",
    }
    assert "launch_pending" not in {item.key for item in MODULE_UI.admin_actions}
    assert "action_required" not in {item.key for item in MODULE_UI.admin_actions}


def test_persistent_meta_page_has_create_settings_and_paginated_select() -> None:
    data = ui._main_payload(
        {
            "items": [{"id": 1, "name": "Meta", "state": "active", "recurrence": "daily"}],
            "page": 0,
            "page_size": 23,
            "total": 24,
        },
        {"notice_channel_id": "10"},
    )
    container = data["components"][0]
    labels = _flatten_labels(container)
    options = [
        option
        for child in container["components"]
        for component in child.get("components", [])
        for option in component.get("options", [])
        if component.get("custom_id") == "yuno:central:v1:meta:select_goal"
    ]
    assert labels == ["Criar Meta", "Configuracoes"]
    assert {item["value"] for item in options} == {"goal:1", "page:next"}
    assert len(options) <= 25


def test_editor_keeps_internal_states_out_of_public_visuals() -> None:
    draft = {
        "revision": 3,
        "step": "review",
        "goal_id": None,
        "data": {
            "name": "Meta",
            "recurrence": "daily",
            "daily_time": "23:55",
            "participation": "all_members",
            "role_ids": [],
            "objectives": [{"kind": "money", "name": "Dinheiro", "money_amount": "10.00"}],
            "notice_text": "Aviso",
        },
    }
    rendered = str(ui._editor_payload(draft)).lower()
    assert "launch_pending" not in rendered
    assert "action_required" not in rendered
    assert "criar meta" in rendered


def test_everyone_is_enabled_only_by_meta_notice_helper() -> None:
    ordinary = payload(text_display("@everyone"))
    notice = meta_notice_payload(text_display("@everyone"))
    assert ordinary["allowed_mentions"] == {"parse": [], "replied_user": False}
    assert notice["allowed_mentions"] == {"parse": ["everyone"], "replied_user": False}


def test_guided_objective_editor_has_structured_actions_and_localized_preview() -> None:
    draft = {
        "revision": 2,
        "step": "objectives",
        "goal_id": None,
        "data": {
            "objective_mode": "mixed",
            "objectives": [
                {
                    "kind": "item",
                    "name": "Arma",
                    "item_quantity": "100000.000",
                    "unit": "unidade",
                    "money_amount": None,
                }
            ],
        },
    }
    data = ui._editor_payload(
        draft,
        products={
            "items": [
                {
                    "id": 7,
                    "name": "Municao",
                    "unit": "caixa",
                    "last_suggested_quantity": "100.000",
                }
            ],
            "page": 0,
            "page_size": 23,
            "total": 1,
        },
    )
    rendered = str(data)
    labels = _flatten_labels(data["components"][0])
    assert "Arma — 100.000 unidades" in rendered
    assert "Usar item cadastrado" in rendered
    assert {"Novo item", "Dinheiro", "Continuar"}.issubset(set(labels))
    assert "separado por |" not in rendered


def test_brazilian_decimal_parser_is_unambiguous() -> None:
    assert ui._parse_decimal_br("10500", places=3) == "10500"
    assert ui._parse_decimal_br("10.500", places=3) == "10500"
    assert ui._parse_decimal_br("10 500", places=3) == "10500"
    assert ui._parse_decimal_br("10,5", places=3) == "10.5"
    assert ui._parse_decimal_br("10.500,250", places=3) == "10500.250"
    assert ui._parse_decimal_br("R$ 1.500,00", places=2, allow_currency=True) == "1500.00"


def test_closed_notice_preserves_visual_content_and_hides_internal_reference() -> None:
    goal = {
        "name": "Meta diaria",
        "current_configuration": {"notice_text": "Aviso"},
    }
    cycle = {
        "id": 17,
        "name": "Meta diaria",
        "notice_text": "Aviso",
        "notice_reference": "meta:1:1",
        "timezone": "America/Sao_Paulo",
        "starts_at": "2026-08-22T07:32:00Z",
        "ends_at": "2026-08-29T03:00:00Z",
        "participants": [{"member_id": "1"}],
        "objectives": [{"kind": "item", "name": "Item", "item_quantity": "100000.000", "unit": "unidade"}],
    }
    active = ui._notice_payload(goal, cycle, ended=False)
    ended = ui._notice_payload(goal, cycle, ended=True)
    assert active["components"][0]["accent_color"] == ended["components"][0]["accent_color"]
    assert active["components"][0]["id"] == ended["components"][0]["id"] == 17
    assert "meta:1:1" not in str(active)
    assert "meta:1:1" not in str(ended)
    assert "Participantes" not in str(active)
    assert "22/08/2026 04:32 → 29/08/2026 00:00" in str(active)
    assert "Item — 100.000 unidades" in str(active)
    assert "Meta Encerrada" in str(ended)
    assert "Encerrada em" not in str(ended)


def test_notice_component_marker_is_found_recursively() -> None:
    components = [{"type": 17, "id": 17, "components": [{"type": 10}]}]
    assert ui._component_contains_id(components, 17)
    assert not ui._component_contains_id(components, 18)


@pytest.mark.asyncio
async def test_meta_notice_nonce_is_sent_with_uniqueness_enforced() -> None:
    class Http:
        body = None

        async def request(self, route, *, json):
            self.body = json
            return {"id": "123"}

    class Bot:
        http = Http()

    bot = Bot()
    message_id = await send_meta_notice(
        bot, 10, meta_notice_payload(text_display("@everyone")), nonce="meta-test"
    )
    assert message_id == 123
    assert bot.http.body["nonce"] == "meta-test"
    assert bot.http.body["enforce_nonce"] is True
