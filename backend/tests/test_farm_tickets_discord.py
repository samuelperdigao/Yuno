import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bot"))

from yuno_bot.domain_modules.farm_tickets import MODULE_UI, ui  # noqa: E402
from yuno_bot.platform.components_v2 import (  # noqa: E402
    FLAG_COMPONENTS_V2,
    media_gallery,
)
from yuno_bot.platform.contracts import ComponentsV2Payload  # noqa: E402
from yuno_bot.platform.router import (  # noqa: E402
    InteractionRouter,
    custom_id,
    parse_custom_id,
)


def _children(data: dict) -> list[dict]:
    return data["components"][0]["components"]


def _rows(data: dict) -> list[dict]:
    return [item for item in _children(data) if item.get("type") == 1]


def _buttons(data: dict) -> list[dict]:
    return [button for row in _rows(data) for button in row["components"]]


def test_farm_ticket_ids_are_stable_module_first_v2_without_breaking_legacy_parser() -> (
    None
):
    value = ui.ticket_custom_id("ticket", "create_entry")
    assert value == "yuno:farm_tickets:v2:ticket:create_entry"
    assert parse_custom_id(value) == {
        "version": 2,
        "module": "farm_tickets",
        "surface": "ticket",
        "action": "create_entry",
    }

    legacy = custom_id("registration", "public", "open_form")
    assert legacy == "yuno:v1:registration:public:open_form"
    assert parse_custom_id(legacy) == {
        "version": 1,
        "module": "registration",
        "surface": "public",
        "action": "open_form",
    }


def test_raw_components_dispatch_handles_only_module_first_v2_without_double_v1() -> (
    None
):
    async def run() -> None:
        router = InteractionRouter(SimpleNamespace())
        router.dispatch = AsyncMock()
        legacy = SimpleNamespace(
            data={"custom_id": "yuno:v1:registration:public:open_form"}
        )
        modern = SimpleNamespace(
            data={"custom_id": "yuno:farm_tickets:v2:ticket:create_entry"}
        )
        assert await router.dispatch_components_v2(legacy) is False
        assert await router.dispatch_components_v2(modern) is True
        router.dispatch.assert_awaited_once_with(
            modern,
            module_key="farm_tickets",
            surface="ticket",
            action_key="create_entry",
        )

    asyncio.run(run())


def test_global_panel_is_components_v2_with_exactly_three_product_buttons() -> None:
    rendered = asyncio.run(ui.render_global({}))
    assert isinstance(rendered, ComponentsV2Payload)
    assert rendered.data["flags"] == FLAG_COMPONENTS_V2
    buttons = _buttons(rendered.data)
    assert [item["label"] for item in buttons] == [
        "Abrir Ticket",
        "Abrir para Membro",
        "Excluir Ticket",
    ]
    assert len(_rows(rendered.data)) == 1
    assert all(
        item["custom_id"].startswith("yuno:farm_tickets:v2:global:") for item in buttons
    )
    visual = str(rendered.data).casefold()
    assert "bem-vind" not in visual
    assert "boas-vindas" not in visual


def test_private_panel_has_exactly_seven_buttons_in_five_plus_two_rows() -> None:
    rendered = asyncio.run(
        ui.render_ticket(
            {
                "ticket": {
                    "member_display_name": "Ana",
                    "status": "IN_PROGRESS",
                    "progress_percent": "35.500",
                }
            }
        )
    )
    rows = _rows(rendered.data)
    assert [len(row["components"]) for row in rows] == [5, 2]
    assert [item["label"] for item in _buttons(rendered.data)] == [
        "Lançar Farm",
        "Editar Lançamento",
        "Ver Comprovantes",
        "Recolhimento",
        "Assumir Ticket",
        "Aprovar Meta",
        "Finalizar Ticket",
    ]
    assert all(
        item["custom_id"].startswith("yuno:farm_tickets:v2:ticket:")
        for item in _buttons(rendered.data)
    )


def test_private_panel_chunks_large_objective_snapshot_under_discord_limits() -> None:
    objectives = [
        {
            "name": f"Objetivo {index} " + "X" * 80,
            "unit": "unidades",
            "target": "1000.000",
            "launched": "500.000",
            "withdrawn": "200.000",
            "available": "300.000",
            "remaining_to_goal": "500.000",
        }
        for index in range(25)
    ]
    rendered = asyncio.run(
        ui.render_ticket(
            {
                "ticket": {
                    "member_id": "100",
                    "member_name": "Ana",
                    "base_nickname": "Ana | 10",
                    "player_id": "10",
                    "goal_name": "Meta semanal",
                    "status": "IN_PROGRESS",
                    "progress_percent": "50.00",
                    "objectives": objectives,
                }
            }
        )
    )
    text_components = [
        item for item in _children(rendered.data) if item.get("type") == 10
    ]
    assert len(text_components) > 2
    assert all(len(item["content"]) <= 4000 for item in text_components)
    assert ui.component_count(rendered.data) <= 40


def test_item_modal_uses_label_components_and_pages_at_five_inputs() -> None:
    objectives = [
        {
            "objective_id": index,
            "name": f"Produto {index}",
            "unit": "unidades",
            "available": index * 10,
        }
        for index in range(1, 13)
    ]

    async def payloads() -> tuple[dict, dict]:
        first = ui.TicketItemsModal(
            panel={"resource_id": "ticket-1"},
            action_key="create_entry",
            items=objectives,
            page=0,
        )
        last = ui.TicketItemsModal(
            panel={"resource_id": "ticket-1"},
            action_key="create_entry",
            items=objectives,
            page=2,
        )
        return first.to_dict(), last.to_dict()

    first, last = asyncio.run(payloads())
    assert first["custom_id"] == "yuno:farm_tickets:v2:ticket:create_entry"
    assert len(first["components"]) == 5
    assert len(last["components"]) == 2
    assert all(item["type"] == 18 for item in first["components"] + last["components"])
    assert all(
        item["component"]["type"] == 4
        for item in first["components"] + last["components"]
    )
    assert all("label" not in item["component"] for item in first["components"])
    assert [item["label"] for item in last["components"]] == [
        "Produto 11",
        "Produto 12",
    ]


def test_reason_modal_also_uses_label_instead_of_legacy_action_row() -> None:
    async def build() -> dict:
        return ui.TicketReasonModal(
            panel={"resource_id": "ticket-1"},
            action_key="finalize",
            title="Finalizar ticket",
        ).to_dict()

    data = asyncio.run(build())
    assert data["components"] == [
        {
            "type": 18,
            "label": "Motivo",
            "component": {
                "type": 4,
                "style": 2,
                "custom_id": "farm_ticket_reason",
                "placeholder": "Descreva o motivo",
                "max_length": 500,
                "required": True,
            },
            "description": "Explique a decisão para o histórico do ticket.",
        }
    ]


def test_proof_gallery_pages_ten_media_and_stays_under_component_limit() -> None:
    proofs = [f"https://cdn.example/{index}.png" for index in range(23)]
    first = ui.proof_gallery_payload(proofs, page=0)
    last = ui.proof_gallery_payload(proofs, page=99)

    first_children = _children(first.data)
    last_children = _children(last.data)
    first_gallery = next(item for item in first_children if item["type"] == 12)
    last_gallery = next(item for item in last_children if item["type"] == 12)
    assert len(first_gallery["items"]) == 10
    assert len(last_gallery["items"]) == 3
    assert ui.component_count(first.data) <= 40
    assert ui.component_count(last.data) <= 40
    assert [item["disabled"] for item in _buttons(first.data)] == [True, False]
    assert [item["disabled"] for item in _buttons(last.data)] == [False, True]
    assert all(
        item["custom_id"].startswith("yuno:farm_tickets:v2:ticket:proofs_")
        for item in _buttons(first.data)
    )
    assert len(media_gallery(proofs + ["https://cdn.example/extra.png"])["items"]) == 10


def test_adapter_is_discoverable_without_touching_the_generic_ticket_module() -> None:
    assert MODULE_UI.module_key == "farm_tickets"
    assert MODULE_UI.contract_version == 2
    assert MODULE_UI.released is True
    assert {item.key for item in MODULE_UI.panels} == {"global", "ticket"}
    assert {item.key for item in MODULE_UI.actions} == {
        "open_ticket",
        "open_for_member",
        "delete_ticket_global",
        "create_entry",
        "edit_entry",
        "list_proofs",
        "proofs_previous",
        "proofs_next",
        "withdraw",
        "assign",
        "approve",
        "finalize",
    }
