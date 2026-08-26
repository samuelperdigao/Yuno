"""Contrato da linguagem visual compartilhada.

O kit é a única camada que os 16 módulos vão importar para desenhar painel, então
o que trava aqui é o que impede um módulo de sair diferente dos outros: o
arredondamento da barra, o mapa de cor por estado, a formatação pt-BR e o teto
de 4000 caracteres por `text_display`.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bot"))

from yuno_bot.platform import ui_kit as uk
from yuno_bot.platform.components_v2 import CONTAINER, SECTION, TEXT_DISPLAY


def _contents(component: dict) -> list[str]:
    result: list[str] = []
    if component.get("type") == TEXT_DISPLAY:
        result.append(component["content"])
    for child in component.get("components") or []:
        result.extend(_contents(child))
    accessory = component.get("accessory")
    if isinstance(accessory, dict):
        result.extend(_contents(accessory))
    return result


def test_progress_bar_only_fills_the_last_block_at_one_hundred_percent() -> None:
    assert uk.progress_bar(0) == uk.EMPTY_BLOCK * 10
    assert uk.progress_bar(49) == uk.FILLED_BLOCK * 4 + uk.EMPTY_BLOCK * 6
    assert uk.progress_bar(50) == uk.FILLED_BLOCK * 5 + uk.EMPTY_BLOCK * 5
    # 99,9% não pode parecer concluído: o preenchimento trunca, nunca arredonda.
    assert uk.progress_bar(99) == uk.FILLED_BLOCK * 9 + uk.EMPTY_BLOCK
    assert uk.progress_bar("99.9") == uk.FILLED_BLOCK * 9 + uk.EMPTY_BLOCK
    assert uk.progress_bar(100) == uk.FILLED_BLOCK * 10
    assert all(len(uk.progress_bar(value)) == 10 for value in range(0, 101))


def test_progress_bar_clamps_out_of_range_and_unreadable_values() -> None:
    assert uk.progress_bar(-30) == uk.EMPTY_BLOCK * 10
    assert uk.progress_bar(180) == uk.FILLED_BLOCK * 10
    assert uk.progress_bar(None) == uk.EMPTY_BLOCK * 10
    assert uk.progress_bar("sem valor") == uk.EMPTY_BLOCK * 10
    assert uk.progress_bar(70, length=5) == uk.FILLED_BLOCK * 3 + uk.EMPTY_BLOCK * 2


def test_status_dot_splits_at_half_and_at_completion() -> None:
    assert uk.status_dot(0) == "🔴"
    assert uk.status_dot("49.999") == "🔴"
    assert uk.status_dot(50) == "🟡"
    assert uk.status_dot("99.9") == "🟡"
    assert uk.status_dot(100) == "✅"
    assert uk.status_dot(None) == "⚪"


def test_progress_block_announces_when_the_percentage_is_unknown() -> None:
    rendered = uk.progress_block("62")
    assert rendered.splitlines()[0] == uk.progress_bar(62)
    assert rendered.splitlines()[1] == "**📊 Progresso geral: 62%**"
    assert uk.progress_block(None) == "**📊 Progresso geral:** Não calculado"
    assert "35,5%" in uk.progress_block("35.500")


def test_accent_for_maps_every_state_and_falls_back_to_the_brand() -> None:
    assert uk.accent_for(uk.State.PENDING) == uk.BRAND
    assert uk.accent_for("running") == uk.WARNING
    assert uk.accent_for("done") == uk.INFO
    assert uk.accent_for("approved") == uk.SUCCESS
    assert uk.accent_for("blocked") == uk.DANGER
    assert uk.accent_for("failed") == uk.DANGER
    assert uk.accent_for("closed") == uk.LOCKED
    assert uk.accent_for("disabled") == uk.NEUTRAL
    assert uk.accent_for(None) == uk.BRAND
    assert uk.accent_for("IN_PROGRESS") == uk.BRAND
    assert uk.accent_for("desconhecido", default=uk.DANGER) == uk.DANGER
    assert set(uk.STATE_ACCENTS) == set(uk.State)
    assert set(uk.STATE_EMOJIS) == set(uk.State)


def test_badge_pairs_the_theme_emoji_with_the_module_label() -> None:
    assert uk.badge(uk.State.RUNNING, "Em andamento") == "🟡 Em andamento"
    assert uk.badge("approved", "Aprovado", bold=True) == "✅ **Aprovado**"
    assert uk.badge(None, "Estado indisponível") == "⚪ Estado indisponível"


def test_brazilian_number_formatting_uses_dot_for_thousands() -> None:
    assert uk.number_br("1234.5") == "1.234,5"
    assert uk.number_br("100000.000") == "100.000"
    assert uk.number_br("1234", places=2, fixed=True) == "1.234,00"
    assert uk.number_br("-1234.5") == "-1.234,5"
    assert uk.number_br(None) == "—"
    assert uk.number_br("abc", fallback="0") == "0"
    assert uk.money_br(1500) == "R$ 1.500,00"
    assert uk.money_br("1234.567") == "R$ 1.234,57"
    assert uk.money_br(None) == "—"


def test_quantity_pluralises_the_unit_only_when_it_should() -> None:
    assert uk.quantity(1, "unidade") == "1 unidade"
    assert uk.quantity(1000, "unidade") == "1.000 unidades"
    assert uk.quantity(3, "caixa") == "3 caixas"
    assert uk.quantity(3, "itens") == "3 itens"
    assert uk.quantity(3, "munição") == "3 munição"
    assert uk.quantity(3) == "3"


def test_timestamp_emits_native_discord_markers_and_degrades_cleanly() -> None:
    assert uk.timestamp("2026-08-29T03:00:00Z") == "<t:1787972400:f>"
    assert uk.timestamp("2026-08-29T03:00:00Z", "R") == "<t:1787972400:R>"
    assert uk.timestamp("") == "Não informado"
    assert uk.timestamp("nao e data", fallback="") == ""


def test_objective_row_carries_health_numbers_and_what_is_left() -> None:
    rendered = uk.objective_row(
        "Ferro",
        "620.000",
        "1000.000",
        unit="unidade",
        remaining="380.000",
        extra=("Recolhido: 200 unidades",),
    )
    lines = rendered.splitlines()
    assert lines[0] == "🟡 **Ferro** — 620/1.000 unidades"
    assert lines[1] == f"{uk.progress_bar(62, length=8)} 62%"
    assert lines[2] == "Restante: 380 unidades · Recolhido: 200 unidades"


def test_objective_row_hides_the_bar_when_there_is_no_target() -> None:
    rendered = uk.objective_row("Ferro", "10", "0")
    assert rendered.splitlines() == ["⚪ **Ferro** — 10/0"]


def test_typography_matches_the_shape_the_modules_already_use() -> None:
    assert uk.heading("Tickets de Farm", emoji="🎫") == "# 🎫 Tickets de Farm"
    assert uk.heading("Resultado", level=3) == "### Resultado"
    assert uk.section_number(1, "Canais", emoji="📍") == "## 📍 1 · Canais"
    assert uk.section_number(2, "Equipe") == "## 2 · Equipe"
    assert uk.field("Membro", "<@1>", emoji="👤") == "**👤 Membro**\n<@1>"
    assert uk.field("Membro", "") == "**Membro**\nNão informado"
    assert uk.inline_fields(("Lançamentos", 4), ("Recolhimentos", 1)) == (
        "**Lançamentos** 4 · **Recolhimentos** 1"
    )
    assert uk.bullet(["a", "", "b"]) == "• a\n• b"
    assert uk.history_line("+150 Ferro", "12/08 14:32") == "• +150 Ferro — 12/08 14:32"
    assert uk.empty_state("Sem meta", "A liderança ainda não definiu.") == (
        "⚠️ **Sem meta**\nA liderança ainda não definiu."
    )


def test_steps_numbers_the_onboarding_and_skips_empty_entries() -> None:
    rendered = uk.steps(("Preencha o ID", "Use o ID do jogo."), ("Aguarde", ""), "", None)
    assert rendered == "1️⃣ **Preencha o ID**\nUse o ID do jogo.\n\n2️⃣ **Aguarde**"
    assert uk.step_marker(10) == "🔟"
    assert uk.step_marker(11) == "**11.**"


def test_ranking_uses_medals_for_the_podium_and_positions_after_it() -> None:
    assert uk.medal(1) == "🥇"
    assert uk.medal(3) == "🥉"
    assert uk.medal(4) == "#4"
    assert uk.ranking_lines([("Ana", "1.234"), ("Bia", None)]) == (
        "🥇 **Ana** — 1.234\n🥈 **Bia**"
    )


def test_subtext_prefixes_every_line_with_the_native_marker() -> None:
    assert uk.subtext("Regra do sistema") == "-# Regra do sistema"
    assert uk.subtext("um\ndois") == "-# um\n-# dois"
    assert uk.subtext("") == ""
    assert uk.subtext(None) == ""


def test_no_helper_ever_exceeds_the_text_display_ceiling() -> None:
    huge = "X" * 9000
    for rendered in (
        uk.heading(huge),
        uk.section_number(1, huge),
        uk.badge(uk.State.RUNNING, huge),
        uk.objective_row(huge, 1, 2),
        uk.empty_state(huge),
    ):
        assert len(rendered) <= uk.TEXT_DISPLAY_LIMIT


def test_long_text_is_split_into_blocks_that_fit_a_text_display() -> None:
    lines = [f"Objetivo {index} " + "X" * 200 for index in range(60)]
    chunks = uk.chunk_lines(lines)
    assert len(chunks) > 1
    assert all(len(chunk) <= uk.CHUNK_LIMIT for chunk in chunks)
    assert "\n\n".join(chunks) == "\n\n".join(lines)

    blocks = uk.text_blocks("\n\n".join(lines))
    assert all(item["type"] == TEXT_DISPLAY for item in blocks)
    assert all(len(item["content"]) <= uk.TEXT_DISPLAY_LIMIT for item in blocks)


def test_avatar_section_degrades_to_plain_text_without_a_https_avatar() -> None:
    with_avatar = uk.avatar_section(
        "**👤 Membro**\n<@1>",
        avatar_url="https://cdn.discordapp.com/a.png",
        description="Foto do membro",
    )
    assert len(with_avatar) == 1
    assert with_avatar[0]["type"] == SECTION
    assert with_avatar[0]["accessory"]["media"]["url"].startswith("https://")

    for url in ("", None, "http://inseguro.example/a.png", "nao-e-url"):
        degraded = uk.avatar_section("**👤 Membro**\n<@1>", avatar_url=url)
        assert [item["type"] for item in degraded] == [TEXT_DISPLAY]

    assert uk.avatar_section(avatar_url="https://cdn.discordapp.com/a.png") == []


def test_panel_keeps_the_canonical_order_and_derives_the_colour_from_the_state() -> None:
    rendered = uk.panel(
        header=uk.heading("Ticket", emoji="🎫"),
        blocks=["identidade", uk.rule(), "dados"],
        actions=[{"type": 1, "components": []}],
        footer="Regra do sistema",
        state=uk.State.RUNNING,
        component_id=17,
    )
    assert rendered["type"] == CONTAINER
    assert rendered["accent_color"] == uk.WARNING
    assert rendered["id"] == 17
    assert [item["type"] for item in rendered["components"]] == [10, 14, 10, 14, 10, 14, 1, 14, 10]
    assert _contents(rendered)[0] == "# 🎫 Ticket"
    assert _contents(rendered)[-1] == "-# Regra do sistema"


def test_panel_skips_empty_blocks_separators_and_footer() -> None:
    rendered = uk.panel(header="# Só o cabeçalho", blocks=["", None, ()], footer="")
    assert [item["type"] for item in rendered["components"]] == [10]
    assert rendered["accent_color"] == uk.BRAND
    assert "id" not in rendered


def test_panel_does_not_choose_the_transport_and_never_mentions_anyone() -> None:
    # `panel` devolve o container; a escolha entre `payload` e
    # `meta_notice_payload` fica com o módulo, que é o que mantém o @everyone
    # restrito à Meta.
    rendered = uk.panel(header="# Aviso")
    assert "flags" not in rendered
    assert "allowed_mentions" not in rendered
