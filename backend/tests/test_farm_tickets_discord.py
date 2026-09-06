import asyncio
import os
import pytest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "bot"))

from app.domain_modules.farm_tickets import (
    definition as backend_definition,  # noqa: E402
)
from yuno_bot.domain_modules.farm_tickets import (  # noqa: E402
    MODULE_UI,
    admin,
    runtime,
    ui,
)
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
    return next(item for item in data["components"] if item.get("type") == 17)["components"]


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


def test_raw_components_dispatch_handles_both_custom_id_formats() -> None:
    """Antes este teste exigia que o formato v1 fosse recusado aqui.

    A premissa era que o DynamicItem do discord.py cobriria os IDs
    version-first, e que aceita-los tambem no dispatcher bruto causaria dispatch
    duplo. Producao refutou a premissa: o discord.py 2.4 nao reconstroi filhos
    aninhados dentro de um container Components V2, entao os tres botoes do
    Registro nao tinham handler nenhum -- a interacao chegava, era logada, e
    nenhuma chamada de API acontecia depois.

    O risco de dispatch duplo continua tratado, so que na camada certa:
    `begin_interaction` e chaveado por `interaction_id` e a segunda passagem
    para em `receipt["duplicate"]` (ver `router.dispatch`).
    """

    async def run() -> None:
        router = InteractionRouter(SimpleNamespace())
        router.dispatch = AsyncMock()
        legacy = SimpleNamespace(
            data={"custom_id": "yuno:v1:registration:public:open_form"}
        )
        modern = SimpleNamespace(
            data={"custom_id": "yuno:farm_tickets:v2:ticket:create_entry"}
        )
        assert await router.dispatch_components_v2(legacy) is True
        assert await router.dispatch_components_v2(modern) is True
        assert router.dispatch.await_count == 2
        router.dispatch.assert_any_await(
            legacy,
            module_key="registration",
            surface="public",
            action_key="open_form",
        )
        router.dispatch.assert_any_await(
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
    with pytest.raises(ValueError, match="1 a 10"):
        media_gallery(proofs + ["https://cdn.example/extra.png"])


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


def _admin_interaction(*, values: list[str] | None = None) -> SimpleNamespace:
    class Response:
        done = False

        def is_done(self) -> bool:
            return self.done

        async def defer(self, **_kwargs) -> None:
            self.done = True

    return SimpleNamespace(
        guild_id=100,
        guild=SimpleNamespace(owner_id=1, me=None),
        user=SimpleNamespace(id=7),
        channel_id=10,
        channel=SimpleNamespace(category_id=None),
        message=SimpleNamespace(id=20),
        client="bot",
        id=555,
        response=Response(),
        data={"values": list(values or [])},
    )


class _AdminAPI:
    def __init__(self, data: dict | None = None, *, published: str | None = None) -> None:
        self.data = dict(data or {})
        self.published = published
        self.saved: list[dict] = []
        self.publishes: list[dict] = []
        self.lifecycles: list[dict] = []

    async def module_instance(self, guild_id, module_key):
        del guild_id, module_key
        return {
            "lifecycle": "active" if self.published else "inactive",
            "published_config_version_id": self.published,
        }

    async def configuration_draft(self, guild_id, module_key):
        del guild_id, module_key
        return {
            "revision": 3,
            "base_published_version": 0,
            "schema_version": 2,
            "data": dict(self.data),
        }

    async def save_configuration_draft(self, guild_id, module_key, payload, *, actor):
        del guild_id, module_key, actor
        self.saved.append(payload)
        self.data = dict(payload["data"])
        return {**payload, "revision": 4}

    async def publish_configuration(self, guild_id, module_key, payload, *, actor):
        del guild_id, module_key, actor
        self.publishes.append(payload)
        return {"version": 1}

    async def update_lifecycle(self, guild_id, module_key, **kwargs):
        del guild_id, module_key
        self.lifecycles.append(kwargs)
        return {"lifecycle": kwargs["lifecycle"]}


def _complete_config() -> dict:
    return {
        "category_id": "900",
        "panel_channel_id": "901",
        "log_channel_id": "902",
        "administrator_role_ids": ["800", "801"],
    }


def test_central_exposes_the_only_path_that_publishes_the_tickets_configuration() -> None:
    assert {item.key for item in MODULE_UI.admin_pages} == {"overview"}
    assert {item.key for item in MODULE_UI.admin_actions} == {
        "overview",
        "open_system",
        "set_category",
        "set_panel_channel",
        "set_log_channel",
        "set_admin_roles",
        "review_publish",
        "confirm_publish",
    }
    for item in MODULE_UI.admin_actions:
        assert len(f"yuno:central:v1:farm_tickets:{item.key}") <= 100


def test_unpublished_overview_offers_configuration_without_leaking_internal_state(
    monkeypatch,
) -> None:
    captured: dict = {}

    async def replace(_interaction, data, **_kwargs):
        captured.update(data)

    monkeypatch.setattr(admin, "_replace_central", replace)
    api = _AdminAPI()

    asyncio.run(admin.render_admin(_admin_interaction(), api))

    children = _children(captured)
    content = "\n".join(item["content"] for item in children if item["type"] == 10)
    action = next(
        item
        for item in children
        if item["type"] == 1 and item["components"][0]["type"] == 2
    )
    assert "Aguardando publicação" in content
    assert "Ainda não definido" in content
    assert "lifecycle" not in content.lower()
    assert "rascunho" not in content.lower()
    assert action["components"][0]["custom_id"] == "yuno:central:v1:farm_tickets:open_system"


def test_administrative_overview_uses_the_nexus_shell_without_decorative_emojis() -> None:
    data = admin.build_admin_payload(
        {"lifecycle": "inactive", "published_config_version_id": None},
        dict(admin.EMPTY_CONFIG),
    )

    assert data["components"][0]["type"] == 12
    rendered = "\n".join(
        item["content"] for item in _children(data) if item.get("type") == 10
    )
    assert "YUNO NEXUS // MODULES / FARM TICKETS" in rendered
    assert "// CONFIGURAÇÃO" in rendered
    assert not any(emoji in rendered for emoji in ("🎫", "⚙️", "📌", "🧭"))
    assert ui.component_count(data) <= 40


def test_configuration_page_selects_cover_the_four_contract_fields(monkeypatch) -> None:
    captured: dict = {}

    async def replace(_interaction, data, **_kwargs):
        captured.update(data)

    monkeypatch.setattr(admin, "_replace_central", replace)

    asyncio.run(admin.open_system(_admin_interaction(), _AdminAPI(_complete_config())))

    selects = [
        row["components"][0]
        for row in _children(captured)
        if row["type"] == 1 and row["components"][0]["type"] in {6, 8}
    ]
    assert [item["custom_id"].rsplit(":", 1)[-1] for item in selects] == [
        "set_category",
        "set_panel_channel",
        "set_log_channel",
        "set_admin_roles",
    ]
    assert selects[0]["channel_types"] == [4]
    assert selects[1]["channel_types"] == [0]
    assert selects[2]["channel_types"] == [0]
    assert selects[3]["max_values"] == 25


def test_partial_selection_only_reaches_the_backend_once_a_role_exists(
    monkeypatch,
) -> None:
    # administrator_role_ids tem min_length 1 no contrato: um rascunho sem cargo
    # seria recusado com 422, entao a selecao parcial fica em memoria de sessao.
    captured: dict = {}

    async def replace(_interaction, data, **_kwargs):
        captured.clear()
        captured.update(data)

    monkeypatch.setattr(admin, "_replace_central", replace)
    admin._pending.clear()
    api = _AdminAPI()

    asyncio.run(admin.set_category(_admin_interaction(values=["900"]), api))
    asyncio.run(admin.set_panel_channel(_admin_interaction(values=["901"]), api))
    assert api.saved == []
    assert admin._pending[(100, 7)]["category_id"] == "900"
    content = "\n".join(
        item["content"]
        for item in _children(captured)
        if item["type"] == 10
    )
    assert "serão gravadas quando ao menos um cargo administrador" in content

    asyncio.run(admin.set_admin_roles(_admin_interaction(values=["800", "800"]), api))

    assert len(api.saved) == 1
    assert api.saved[0]["data"] == {
        "category_id": "900",
        "panel_channel_id": "901",
        "log_channel_id": "",
        "administrator_role_ids": ["800"],
    }
    assert api.saved[0]["expected_revision"] == 3
    assert api.saved[0]["schema_version"] == 2
    assert (100, 7) not in admin._pending
    admin._pending.clear()


def test_published_grants_satisfy_the_backend_permission_validator() -> None:
    assert admin.ADMIN_CAPABILITIES == backend_definition.ADMIN_CAPABILITIES

    config = _complete_config()
    grants = [SimpleNamespace(**item) for item in admin.build_grants(config)]

    assert backend_definition._validate_permission_grants(config, grants) == []
    assert len(grants) == 1 + len(backend_definition.ADMIN_CAPABILITIES) * 2

    stale = backend_definition._validate_permission_grants(
        {**config, "administrator_role_ids": ["800", "801", "802"]}, grants
    )
    assert stale and all("cargos administradores" in item for item in stale)


def test_preflight_blocks_publication_on_missing_fields_and_dead_resources() -> None:
    guild = SimpleNamespace(
        me=None,
        get_channel=lambda _id: None,
        get_role=lambda _id: None,
    )

    errors = admin.preflight(guild, dict(admin.EMPTY_CONFIG))

    assert [item for item in errors if "Categoria principal" in item]
    assert [item for item in errors if "Canal do painel" in item]
    assert [item for item in errors if "Canal de logs" in item]
    assert [item for item in errors if "Cargos administradores" in item]

    dead = admin.preflight(guild, _complete_config())
    assert "A categoria principal não existe mais neste servidor." in dead
    assert [item for item in dead if "Cargo administrador inexistente" in item]

    same_channel = admin.preflight(
        guild, {**_complete_config(), "log_channel_id": "901"}
    )
    assert "O painel e os logs precisam de canais diferentes." in same_channel


def test_confirm_publish_is_refused_before_the_resources_exist(monkeypatch) -> None:
    sent: list[str] = []

    async def send_error(_interaction, message):
        sent.append(message)

    monkeypatch.setattr(admin, "_send_interaction_error", send_error)
    admin._pending.clear()
    api = _AdminAPI(_complete_config())
    interaction = _admin_interaction()
    interaction.guild = SimpleNamespace(
        owner_id=1, me=None, get_channel=lambda _id: None, get_role=lambda _id: None
    )

    asyncio.run(admin.confirm_publish(interaction, api))

    assert api.publishes == []
    assert api.lifecycles == []
    assert sent and sent[0].startswith("Publicação bloqueada:")


def test_reconcile_skips_provisioning_while_configuration_is_unpublished() -> None:
    calls: list[str] = []

    class PlatformAPI:
        async def module_instance(self, guild_id, module_key):
            calls.append(f"instance:{guild_id}:{module_key}")
            return {"lifecycle": "inactive", "published_config_version_id": None}

        async def effective_configuration(self, guild_id, module_key):
            raise AssertionError("nao pode buscar configuracao publicada inexistente")

    bot = SimpleNamespace(
        get_guild=lambda _id: SimpleNamespace(id=100),
        user=SimpleNamespace(id=42),
    )

    result = asyncio.run(
        runtime.run_job(
            bot,
            PlatformAPI(),
            {
                "id": "startup:100",
                "guild_id": "100",
                "key": "farm_tickets.reconcile",
                "resource_id": "100",
                "correlation_id": "startup:farm-tickets:100",
                "payload": {"reason": "startup"},
            },
        )
    )

    assert result == {"skipped": "unpublished_configuration"}
    assert calls == ["instance:100:farm_tickets"]
