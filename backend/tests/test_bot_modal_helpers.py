import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "bot"))

from yuno_bot.commands.adv.embeds import adv_log_embed, adv_post_embed, build_adv_payload
from yuno_bot.commands.encomenda.embeds import build_encomenda_payload
from app.services import check_permission
from yuno_bot.commands.ausencia.embeds import (
    ausencia_channel_id,
    ausencias_list_embed,
    build_ausencia_setup_config,
    dias_restantes,
    format_date_br,
    normalize_motivo,
    parse_dias,
)
from yuno_bot.commands.farm_tickets.helpers import (
    current_week_id,
    is_farm_admin,
    member_folder_nickname_and_game_id,
    next_folder_slot,
    parse_discord_ids,
    parse_member_folder,
)
from yuno_bot.commands.farm_tickets.views import FarmPanelView
from yuno_bot.commands.meta.embeds import (
    build_meta_definition_text,
    build_meta_panel_config,
    build_meta_payload,
    meta_definition_embed,
    parse_meta_definition,
)
from yuno_bot.commands.parceria.embeds import build_parceria_payload
from yuno_bot.commands.parceria.embeds import (
    format_brazilian_date,
    is_valid_image_attachment,
    parceria_active_embed,
    parcerias_panel_embed,
    uniform_filename,
)
from yuno_bot.commands.parceria.permissions import member_has_named_management_role, role_name_matches
from yuno_bot.commands.parceria.repository import ParceriaDuplicadaError, ParceriasRepository
from yuno_bot.commands.producao.embeds import build_producao_payload
from yuno_bot.commands.set.embeds import build_set_panel_config, build_set_payload, panel_embed
from yuno_bot.commands.shared import log_channel_id_from_setup, parse_positive_int, send_module_log
from yuno_bot.server_setup import build_setup_config, log_channels, module_keys


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
        **{f"log_{module}": SimpleNamespace(id=100 + index) for index, module in enumerate(log_channels())},
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

    # Derivado do registry em vez de indices fixos: assim o teste continua
    # valido quando um modulo novo entra no meio da ordem.
    esperado = {module: str(100 + index) for index, module in enumerate(log_channels())}
    assert setup["log_channel_ids"] == esperado

    # Todo modulo do registry precisa aparecer em `modules`, senao o cliente
    # nao consegue liga-lo nem desliga-lo.
    assert set(config["modules"]) == set(module_keys())
    assert all(config["modules"].values())


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
    assert build_adv_payload(42, "  Faltou ao turno  ", 7) == {"membro_id": "42", "descricao": "Faltou ao turno", "dias": 7}


def test_adv_embeds_show_membro_and_duracao() -> None:
    membro = SimpleNamespace(
        mention="<@42>", display_name="Mineiro", id=42, display_avatar=SimpleNamespace(url="https://example.com/a.png")
    )
    interaction = SimpleNamespace(
        user=SimpleNamespace(mention="<@1>", id=1, display_name="Admin"),
        channel=SimpleNamespace(mention="<#9>"),
    )
    payload = build_adv_payload(membro.id, "Descumpriu regra", 3)
    record = {"id": 55}

    post = adv_post_embed(interaction, record, membro, payload).to_dict()
    assert post["fields"][0]["value"] == "#55"
    assert "Mineiro" in post["fields"][1]["value"]
    assert "3" in post["fields"][2]["value"]

    log_embed = adv_log_embed(interaction, record, membro, payload).to_dict()
    assert any(field["name"] == "Membro" and "42" in field["value"] for field in log_embed["fields"])


def test_parse_meta_definition_accepts_multiple_items() -> None:
    items = parse_meta_definition("item, 10\nitem, 1.250")
    assert items == [
        {"name": "item", "quantity": 10},
        {"name": "item", "quantity": 1250},
    ]
    assert build_meta_definition_text(items) == "item, 10\nitem, 1250"


def test_parse_meta_definition_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="formato item, quantidade"):
        parse_meta_definition("item 10")
    with pytest.raises(ValueError, match="Quantidade deve conter apenas numeros"):
        parse_meta_definition("item, abc")
    with pytest.raises(ValueError, match="maior que zero"):
        parse_meta_definition("item, 0")
    with pytest.raises(ValueError, match="no maximo 20"):
        parse_meta_definition("\n".join(f"item, {index + 1}" for index in range(21)))
    with pytest.raises(ValueError, match="80 caracteres"):
        parse_meta_definition(f"{'A' * 81}, 1")


def test_meta_panel_config_saves_channels_role_message_and_last_definition() -> None:
    config = build_meta_panel_config(
        {
            "guild_name": "Cidade Setup",
            "admin_role_ids": ["admin-role"],
            "log_channel_id": "logs",
            "modules": {"meta": True},
            "command_permissions": {
                "meta.registrar": {"channel_ids": ["old-channel"]},
                "meta.definir": {"category_ids": ["old-category"]},
            },
            "messages": {"hello": "world"},
            "settings": {"discord_setup": {"channel_ids": {"metas": "metas-channel"}}},
        },
        panel_channel_id=11,
        result_channel_id=12,
        allowed_role_id=99,
        panel_message_id=1234,
        last_definition_text="item, 10",
    )

    assert config["command_permissions"]["meta.definir"]["channel_ids"] == ["11"]
    assert config["command_permissions"]["meta.definir"]["role_ids"] == ["99"]
    assert config["command_permissions"]["meta.definir"]["category_ids"] == ["old-category"]
    assert config["command_permissions"]["meta.registrar"]["channel_ids"] == ["old-channel"]
    assert config["settings"]["meta"]["panel_channel_id"] == "11"
    assert config["settings"]["meta"]["result_channel_id"] == "12"
    assert config["settings"]["meta"]["allowed_role_id"] == "99"
    assert config["settings"]["meta"]["panel_message_id"] == "1234"
    assert config["settings"]["meta"]["last_definition_text"] == "item, 10"
    assert config["settings"]["discord_setup"]["channel_ids"]["metas"] == "metas-channel"


def test_meta_definir_permission_uses_configured_role_and_channel() -> None:
    config = SimpleNamespace(
        modules={"meta": True},
        admin_role_ids=[],
        command_permissions={"meta.definir": {"role_ids": ["99"], "channel_ids": ["11"]}},
    )

    assert check_permission(config, module="meta", command="definir", user_role_ids=["99"], channel_id="11", category_id=None) == (
        True,
        "Permitido.",
    )
    assert check_permission(config, module="meta", command="definir", user_role_ids=["98"], channel_id="11", category_id=None) == (
        False,
        "Cargo sem permissao para este comando.",
    )
    assert check_permission(config, module="meta", command="definir", user_role_ids=["99"], channel_id="10", category_id=None) == (
        False,
        "Canal sem permissao para este comando.",
    )


def test_meta_definition_embed_lists_multiple_items() -> None:
    interaction = SimpleNamespace(user=SimpleNamespace(mention="<@42>", id=42), guild=SimpleNamespace(name="Cidade Yuno"))
    embed = meta_definition_embed(interaction, {"id": 123}, [{"name": "item", "quantity": 10}, {"name": "item", "quantity": 20}])
    data = embed.to_dict()

    assert data["title"] == "🎯 Meta definida"
    assert "Cidade Yuno" in data["description"]
    assert "Protocolo" not in str(data)
    assert "Responsavel" not in str(data)
    assert "🔸 **item**" in data["fields"][0]["value"]
    assert "Quantidade: `10`" in data["fields"][0]["value"]
    assert "Quantidade: `20`" in data["fields"][0]["value"]


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


def test_parcerias_image_helpers_and_date_format() -> None:
    assert uniform_filename("Comando Vermelho", "foto.PNG") == "uniforme_comando-vermelho.png"
    assert uniform_filename("Família São João", "uniforme.webp") == "uniforme_familia-sao-joao.webp"
    assert is_valid_image_attachment("uniforme.gif", None) is True
    assert is_valid_image_attachment("arquivo.txt", "image/png") is True
    assert is_valid_image_attachment("arquivo.txt", "text/plain") is False
    assert format_brazilian_date("2026-07-23 18:40:00") == "23/07/2026 às 18:40"


def test_parcerias_embeds_match_requested_layout() -> None:
    panel_data = parcerias_panel_embed().to_dict()
    assert panel_data["title"] == "Painel de Parcerias"
    assert "registrar, editar ou remover" in panel_data["description"]
    assert panel_data["footer"]["text"] == "Sistema de Parcerias"
    assert panel_data["fields"][0]["name"] == "Registro"
    assert panel_data["fields"][1]["name"] == "Lista ativa"

    active_data = parceria_active_embed(
        {
            "nome_familia": "Comando Vermelho",
            "produto": "Armamento",
            "contato_01": "João: (31) 99999-9999",
            "contato_02": "",
            "criado_em": "2026-07-23 18:40:00",
        },
        attachment_filename="uniforme_comando-vermelho.png",
    ).to_dict()
    assert active_data["title"] == "Comando Vermelho"
    assert active_data["color"] == 16766720
    assert active_data["fields"][0]["name"] == "🛒 Produto"
    assert active_data["image"]["url"] == "attachment://uniforme_comando-vermelho.png"
    assert active_data["footer"]["text"] == "Parceria registrada em 23/07/2026 às 18:40"


def test_parcerias_role_name_permissions() -> None:
    assert role_name_matches("Gerente Geral") is True
    assert role_name_matches("Equipe de Aprovação") is True
    assert role_name_matches("Membro") is False

    member = SimpleNamespace(roles=[SimpleNamespace(name="Membro"), SimpleNamespace(name="Editor de Parcerias")])
    assert member_has_named_management_role(member) is True


@pytest.mark.asyncio
async def test_parcerias_repository_translates_conflict_and_tolerates_network_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """`ParceriasRepository` fala HTTP com o backend (ver test_api.py para o ciclo de vida completo).

    Aqui cobrimos so a traducao de erro que a camada HTTP acrescenta: 409 vira
    `ParceriaDuplicadaError` e falha de rede numa leitura vira `None`/lista
    vazia em vez de propagar, porque os call-sites em views.py tratam ausencia
    de dado, nao excecao de transporte.
    """
    repository = ParceriasRepository()

    class FakeResponse:
        def __init__(self, status_code: int, payload=None) -> None:
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise httpx.HTTPStatusError("erro", request=None, response=self)

    async def fake_post_conflict(self, *args, **kwargs):
        return FakeResponse(409)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post_conflict)
    with pytest.raises(ParceriaDuplicadaError):
        await repository.create_parceria(
            guild_id=123,
            nome_familia="Comando Vermelho",
            produto="Armamento",
            contato_01=None,
            contato_02=None,
            mensagem_lista_id=999,
            nome_arquivo_imagem="uniforme.png",
            registrado_por=42,
        )

    async def fake_get_unavailable(self, *args, **kwargs):
        raise httpx.ConnectError("sem rede")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get_unavailable)
    assert await repository.get_config(123) is None
    assert await repository.list_active(123) == []
    assert await repository.name_exists_for_other(123, "Comando Vermelho", 1) is False


def test_parse_positive_int_rejects_invalid_values() -> None:
    assert parse_positive_int("1.250", "Quantidade") == 1250
    with pytest.raises(ValueError):
        parse_positive_int("abc", "Quantidade")
    with pytest.raises(ValueError):
        parse_positive_int("0", "Quantidade")


def test_ausencia_helpers_validate_days_motivo_dates_and_config() -> None:
    assert parse_dias("5") == 5
    with pytest.raises(ValueError, match="apenas o número de dias"):
        parse_dias("5 dias")
    with pytest.raises(ValueError, match="pelo menos 1"):
        parse_dias("0")
    with pytest.raises(ValueError, match="acima de 7 dias"):
        parse_dias("8")

    assert normalize_motivo("") == "Não informado"
    fim = datetime(2026, 7, 25, tzinfo=timezone.utc)
    now = datetime(2026, 7, 23, 12, tzinfo=timezone.utc)
    assert format_date_br(fim) == "25/07/2026"
    assert dias_restantes(fim, now) == 2

    config = build_ausencia_setup_config(
        {"settings": {"discord_setup": {"channel_ids": {"metas": "10"}}}, "modules": {"ausencia": True}},
        channel_id=99,
    )
    assert config["settings"]["ausencia"]["canal_ausencias_id"] == "99"
    assert config["settings"]["discord_setup"]["channel_ids"]["metas"] == "10"
    assert ausencia_channel_id(config) == 99


def test_ausencias_list_embed_uses_active_record_fields() -> None:
    fim = datetime.now(timezone.utc) + timedelta(days=2)
    embed = ausencias_list_embed(
        [
            {
                "guild_id": "1",
                "user_id": "42",
                "nome": "Ana",
                "dias": 3,
                "motivo": "Viagem",
                "inicio": datetime.now(timezone.utc).isoformat(),
                "fim": fim.isoformat(),
                "avisado": 0,
                "message_id": None,
            }
        ]
    )
    data = embed.to_dict()
    assert data["title"] == "📋 Membros em Ausência"
    assert data["fields"][0]["name"] == "👤 Ana"
    assert "Motivo: Viagem" in data["fields"][0]["value"]


def test_farm_ticket_helpers_parse_ids_week_and_admin_permissions() -> None:
    assert parse_discord_ids("<#123>, 456, <@&789>") == [123, 456, 789]
    assert current_week_id(datetime(2026, 7, 23, 12, tzinfo=timezone.utc)) == "2026-W30"
    folder = parse_member_folder("┃📁-7-mineiro-6627", 500)
    assert (folder.channel_id, folder.slot, folder.nickname, folder.game_id) == (500, 7, "Mineiro", "6627")
    category = SimpleNamespace(
        text_channels=[
            SimpleNamespace(name="┃📁-1-ana-111", id=1),
            SimpleNamespace(name="┃📁-2-bruno-222", id=2),
        ]
    )
    assert next_folder_slot(category) == 3
    member_identity = SimpleNamespace(display_name="Mineiro | 6627", name="Mineiro", id=42)
    assert member_folder_nickname_and_game_id(member_identity) == ("Mineiro", "6627")

    member = SimpleNamespace(
        guild_permissions=SimpleNamespace(manage_guild=False, administrator=False),
        roles=[SimpleNamespace(id=99)],
    )
    assert is_farm_admin(member, {"admin_role_ids": ["99"]}) is True
    assert is_farm_admin(member, {"admin_role_ids": ["98"]}) is False


@pytest.mark.asyncio
async def test_farm_panel_view_has_open_weekly_ticket_button() -> None:
    view = FarmPanelView(SimpleNamespace())
    labels = [child.label for child in view.children]
    custom_ids = [child.custom_id for child in view.children]
    assert "Abrir Ticket Semanal" in labels
    assert "yuno:farm:panel:open" in custom_ids


@pytest.mark.asyncio
async def test_send_module_log_returns_false_without_configured_channel() -> None:
    class FakeApi:
        async def get_guild_config(self, guild_id: int) -> dict:
            return {"settings": {"discord_setup": {"log_channel_ids": {}}}, "log_channel_id": None}

    interaction = SimpleNamespace(guild=SimpleNamespace(id=123))
    assert await send_module_log(FakeApi(), interaction, "set", SimpleNamespace()) is False
    assert log_channel_id_from_setup({"settings": {"discord_setup": {"log_channel_ids": {}}}}, "set") is None
