"""Testes do painel de status (Fase 1 do plano de fundacao).

O painel nao reimplementa a configuracao de cada modulo (ver docstring de
dashboard.py) -- o que precisa estar certo aqui e o calculo de estado
(configurado/incompleto/desligado) e onde cada modulo guarda seus valores,
porque isso e o unico "codigo novo" real; o resto e so payload.
"""

import os
import sys
import asyncio
from pathlib import Path

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "bot"))

from yuno_bot import dashboard
from yuno_bot.commands.panels import customize_panel_embed, with_panel_config
from yuno_bot.modules import DashboardField, ModuleSpec

SPEC_UM_CAMPO = ModuleSpec(
    key="teste",
    nome="Modulo Teste",
    descricao="desc",
    dashboard_fields=(DashboardField("panel_channel_id", "Canal", "channel"),),
)

SPEC_SEM_CAMPOS = ModuleSpec(key="teste_simples", nome="Simples", descricao="desc")

SPEC_COM_OPCIONAL = ModuleSpec(
    key="teste_opcional",
    nome="Modulo Opcional",
    descricao="desc",
    dashboard_fields=(
        DashboardField("panel_channel_id", "Canal", "channel"),
        DashboardField("extra_role_ids", "Cargos extra", "roles", obrigatorio=False),
    ),
)


def test_modulo_desligado_e_desligado_independente_de_campos() -> None:
    config = {"modules": {"teste": False}, "settings": {"teste": {"panel_channel_id": "123"}}}
    assert dashboard.compute_status(SPEC_UM_CAMPO, config) == "desligado"


def test_modulo_ligado_sem_valor_obrigatorio_e_incompleto() -> None:
    config = {"modules": {"teste": True}, "settings": {}}
    assert dashboard.compute_status(SPEC_UM_CAMPO, config) == "incompleto"


def test_modulo_ligado_com_valor_obrigatorio_e_configurado() -> None:
    config = {"modules": {"teste": True}, "settings": {"teste": {"panel_channel_id": "123"}}}
    assert dashboard.compute_status(SPEC_UM_CAMPO, config) == "configurado"


def test_modulo_sem_dashboard_fields_e_configurado_assim_que_ligado() -> None:
    config = {"modules": {"teste_simples": True}, "settings": {}}
    assert dashboard.compute_status(SPEC_SEM_CAMPOS, config) == "configurado"


def test_campo_opcional_faltando_nao_impede_configurado() -> None:
    config = {"modules": {"teste_opcional": True}, "settings": {"teste_opcional": {"panel_channel_id": "123"}}}
    assert dashboard.compute_status(SPEC_COM_OPCIONAL, config) == "configurado"


def test_campo_obrigatorio_com_lista_vazia_e_incompleto() -> None:
    config = {"modules": {"teste": True}, "settings": {"teste": {"panel_channel_id": []}}}
    assert dashboard.compute_status(SPEC_UM_CAMPO, config) == "incompleto"


def test_module_values_le_settings_do_proprio_modulo_para_modulo_com_painel() -> None:
    config = {"settings": {"set": {"panel_channel_id": "11", "approval_role_id": "22"}}}
    assert dashboard.module_values("set", config) == {"panel_channel_id": "11", "approval_role_id": "22"}


def test_module_values_le_discord_setup_para_modulo_sem_comando_de_painel() -> None:
    config = {"settings": {"discord_setup": {"channel_ids": {"encomendas": "999"}}}}
    assert dashboard.module_values("encomenda", config) == {"panel_channel_id": "999"}


def test_module_values_modulo_sem_setup_channels_correspondentes_retorna_vazio() -> None:
    assert dashboard.module_values("encomenda", {"settings": {}}) == {}


def test_module_info_embed_formata_lista_de_cargos_como_multiplas_mencoes() -> None:
    spec = ModuleSpec(
        key="teste_lista",
        nome="Modulo Lista",
        descricao="desc",
        dashboard_fields=(DashboardField("admin_role_ids", "Cargos", "roles"),),
    )
    config = {"modules": {"teste_lista": True}, "settings": {"teste_lista": {"admin_role_ids": ["1", "2"]}}}
    embed = dashboard.module_info_embed(spec, config)
    campo_cargos = next(f for f in embed.fields if f.name == "Cargos")
    assert campo_cargos.value == "<@&1> <@&2>"


def test_module_info_embed_incompleto_mostra_comando_de_como_resolver() -> None:
    config = {"modules": {"set": True}, "settings": {}}
    from yuno_bot.modules import get_module

    spec = get_module("set")
    embed = dashboard.module_info_embed(spec, config)
    campo_resolver = next(f for f in embed.fields if f.name == "Como resolver")
    assert "/set painel" in campo_resolver.value


def test_build_payload_pagina_todos_os_modulos_do_registry() -> None:
    from yuno_bot.modules import discover_modules

    config = {"modules": {key: True for key in discover_modules()}, "settings": {}}
    payloads = [dashboard.build_payload(config, page) for page in range(dashboard._page_count())]

    assert all(payload["flags"] == dashboard._FLAG_V2 for payload in payloads)
    custom_ids = set()
    for payload in payloads:
        def component_count(component: dict) -> int:
            children = component.get("components") or []
            accessory = component.get("accessory")
            return 1 + sum(component_count(child) for child in children) + (
                component_count(accessory) if accessory else 0
            )

        assert sum(component_count(component) for component in payload["components"]) <= 30
        container = payload["components"][0]
        sections = [
            component
            for component in container["components"]
            if component.get("type") == dashboard._SECTION
        ]
        assert len(sections) <= dashboard._PAGE_SIZE
        custom_ids.update(component["accessory"]["custom_id"] for component in sections)
    assert custom_ids == {f"yuno:painel:info:{key}" for key in discover_modules()}


def test_dashboard_message_ref_and_with_dashboard_ref_roundtrip() -> None:
    config = {"settings": {}}
    updated = dashboard.with_dashboard_ref(config, channel_id=111, message_id=222)
    assert dashboard.dashboard_message_ref(updated) == (111, 222)
    assert dashboard.dashboard_message_ref({"settings": {}}) == (None, None)


def test_dispatcher_do_painel_e_persistente_e_cobre_paginas() -> None:
    async def build():
        return dashboard.PainelDispatcherView(object())

    view = asyncio.run(build())
    assert view.is_persistent()
    assert len(view.children) == len(dashboard.discover_modules()) + dashboard._page_count()


def test_personalizacao_do_painel_consume_messages_da_guild() -> None:
    import discord

    embed = discord.Embed(title="Padrao", description="Padrao", color=0)
    config = {
        "messages": {
            "ticket": {
                "panel": {"title": "Central da Cidade", "description": "Abra seu chamado.", "color": "#123ABC"}
            }
        }
    }

    customized = customize_panel_embed(embed, config, "ticket")
    assert customized.title == "Central da Cidade"
    assert customized.description == "Abra seu chamado."
    assert customized.color.value == 0x123ABC


def test_with_panel_config_salva_referencia_e_restringe_comando() -> None:
    updated = with_panel_config(
        {"modules": {"ticket": True}, "settings": {}, "command_permissions": {}},
        module_key="ticket",
        channel_id=10,
        message_id=20,
        command_names=("abrir",),
        role_ids=(30,),
    )

    assert updated["settings"]["ticket"] == {
        "panel_channel_id": "10",
        "panel_message_id": "20",
        "role_ids": ["30"],
    }
    assert updated["command_permissions"]["ticket.abrir"] == {
        "channel_ids": ["10"],
        "role_ids": ["30"],
    }
