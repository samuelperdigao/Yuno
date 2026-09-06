import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bot"))

from yuno_bot import dashboard  # noqa: E402
from yuno_bot.domain_modules.parceria import MODULE_UI  # noqa: E402
from yuno_bot.domain_modules.parceria.admin import build_admin_payload  # noqa: E402
from yuno_bot.domain_modules.parceria.runtime import _embed  # noqa: E402
from yuno_bot.platform.registry import discover_ui_modules  # noqa: E402


def _rows(data: dict) -> dict[str, dict]:
    return {
        item["accessory"]["custom_id"].split(":")[-2]: item
        for item in data["components"][0]["components"]
        if item["type"] == 9
    }


def test_parceria_entra_na_central_pelo_comando_yuno_configurar() -> None:
    discover_ui_modules()
    specs = dashboard.dashboard_specs()
    rows = _rows(dashboard.build_payload({}))

    assert "parceria" in specs
    assert rows["parceria"]["accessory"]["custom_id"] == "yuno:central:v1:parceria:open"
    options = dashboard.module_navigation("parceria")["components"][0]["options"]
    parceria = next(item for item in options if item["value"] == "parceria")
    assert parceria["default"] is True


def test_parceria_declares_admin_page_operational_panel_jobs_and_deliveries() -> None:
    assert MODULE_UI.released is True
    assert {item.key for item in MODULE_UI.admin_pages} == {"overview"}
    assert {item.key for item in MODULE_UI.panels} == {"global"}
    assert {item.key for item in MODULE_UI.jobs} == {
        "parceria.registration.expire",
        "parceria.panel.reconcile",
        "parceria.publication.reconcile",
        "parceria.publication.retry",
    }
    assert {item.key for item in MODULE_UI.deliveries} == {
        "parceria.publication",
        "parceria.panel",
        "parceria.log",
    }
    assert {item.key for item in MODULE_UI.actions} >= {
        "register",
        "submit_registration",
        "edit",
        "edit_submit",
        "deactivate",
        "deactivate_confirm",
    }


def test_parceria_operational_panel_uses_components_v2_and_stable_ids() -> None:
    async def scenario() -> dict:
        rendered = await MODULE_UI.panels[0].renderer(
            {"config": {"registrar_channel_id": "123"}, "config_version": 1}
        )
        return rendered.data

    data = asyncio.run(scenario())
    serialized = str(data)
    assert "yuno:parceria:v1:global:register" in serialized
    assert "yuno:parceria:v1:global:edit" in serialized
    assert "yuno:parceria:v1:global:deactivate" in serialized


def test_parceria_admin_payload_uses_components_v2_header_components() -> None:
    discover_ui_modules()

    data = build_admin_payload({}, {"data": {}})

    header = data["components"][0]["components"][:3]
    assert header[0]["type"] == 1
    assert header[1]["type"] == 14
    assert header[2]["type"] == 10


def test_parceria_publication_embed_references_the_uploaded_attachment() -> None:
    embed = _embed(
        {
            "id": "parceria-1",
            "family_name": "Morro do Mineiro",
            "product_name": "Coletes",
            "contacts": ["999999"],
            "image": {"original_filename": "uniforme.png"},
        },
        image_url="attachment://uniforme.png",
    )

    assert embed.image.url == "attachment://uniforme.png"
