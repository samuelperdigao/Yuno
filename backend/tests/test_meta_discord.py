from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bot"))

from yuno_bot.domain_modules.meta import MODULE_UI
from yuno_bot.domain_modules.meta import ui
from yuno_bot.platform.components_v2 import meta_notice_payload, payload, text_display


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


def test_closed_notice_preserves_layout_color_and_reference_without_extra_time() -> None:
    goal = {
        "name": "Meta diaria",
        "current_configuration": {"notice_text": "Aviso"},
    }
    cycle = {
        "name": "Meta diaria",
        "notice_text": "Aviso",
        "notice_reference": "meta:1:1",
        "participants": [{"member_id": "1"}],
        "objectives": [{"kind": "item", "name": "Item", "item_quantity": "10.000", "unit": "unidade"}],
    }
    active = ui._notice_payload(goal, cycle, ended=False)
    ended = ui._notice_payload(goal, cycle, ended=True)
    assert active["components"][0]["accent_color"] == ended["components"][0]["accent_color"]
    assert "meta:1:1" in str(ended)
    assert "Meta Encerrada" in str(ended)
    assert "Encerrada em" not in str(ended)
