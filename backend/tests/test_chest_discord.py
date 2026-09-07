import asyncio
from types import SimpleNamespace

from yuno_bot import dashboard
from yuno_bot.domain_modules.chest import MODULE_UI, ui
from yuno_bot.platform.components_v2 import component_count
from yuno_bot.platform.contracts import ActorContext, RoutedContext
from yuno_bot.platform.router import parse_custom_id


def actor():
    return ActorContext(
        guild_id=100,
        user_id=900,
        role_ids=(),
        discord_permissions=(),
        channel_id=10,
        category_id=None,
        actor_type="user",
        is_guild_owner=False,
        correlation_id="discord-test",
    )


def test_chest_public_panel_is_nexus_v2_and_persistent():
    rendered = asyncio.run(
        ui.render_global(
            {
                "config": {
                    "panel_title": "Sistema de Bau",
                    "panel_description": "Estoque da organizacao.",
                }
            }
        )
    ).data
    assert "YUNO NEXUS // RUNTIME / CHEST" in str(rendered)
    assert "yuno:chest:v1:global:select_chest" in str(rendered)
    assert "yuno:chest:v1:global:history_own" in str(rendered)
    assert component_count(rendered["components"]) <= 40
    panel = MODULE_UI.panels[0]
    assert panel.key == "global"
    assert panel.recovery_policy == "automatic"


def test_chest_catalog_with_more_than_25_entries_is_paginated():
    class API:
        async def chest_catalog(self, guild_id, *, actor):
            return {
                "chests": [
                    {
                        "id": f"00000000-0000-0000-0000-{index:012d}",
                        "name": f"Bau {index}",
                        "active": True,
                    }
                    for index in range(30)
                ]
            }

    context = RoutedContext(
        interaction=SimpleNamespace(guild=SimpleNamespace(id=100)),
        actor=actor(),
        panel={"module_key": "chest", "panel_key": "global"},
        api=API(),
        receipt_id="receipt",
    )
    result = asyncio.run(ui.select_chest(context))
    data = result.components_v2.data
    selects = []

    def visit(value):
        if isinstance(value, dict):
            if value.get("type") == 3:
                selects.append(value)
            for child in value.get("components", []):
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(data)
    assert len(selects[0]["options"]) == 23
    assert "1/2" in selects[0]["placeholder"]
    assert component_count(data["components"]) <= 40


def test_chest_modal_custom_ids_use_the_modern_router():
    context = RoutedContext(
        interaction=SimpleNamespace(guild=SimpleNamespace(id=100)),
        actor=actor(),
        panel={"module_key": "chest", "panel_key": "global"},
        api=object(),
        receipt_id="receipt",
    )
    ui._sessions[(100, 900)] = {"chest_id": "00000000-0000-0000-0000-000000000001"}

    async def build_modal():
        return ui.MovementModal(
            context=context,
            mode="withdraw",
            item_id="00000000-0000-0000-0000-000000000002",
        )

    modal = asyncio.run(build_modal())
    parsed = parse_custom_id(modal.custom_id)
    assert parsed == {
        "version": 1,
        "module": "chest",
        "surface": "global",
        "action": "withdraw_submit",
    }
    assert modal.timeout == 600
    assert modal.observation.required is True

    ui._sessions[(100, 900)]["withdrawal_reason_required"] = False
    optional = asyncio.run(build_modal())
    assert optional.observation.required is False


def test_chest_is_exposed_by_nexus_with_grouped_admin_actions():
    specs = dashboard.dashboard_specs()
    assert specs["chest"].nome == "Sistema de Bau"
    actions = {item.key for item in MODULE_UI.admin_actions}
    assert {
        "inventory",
        "access",
        "configuration",
        "diagnose",
        "recover",
        "publish",
    } <= actions
    assert not any("slash" in item.key for item in MODULE_UI.actions)
