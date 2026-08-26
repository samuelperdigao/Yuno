"""Linguagem visual compartilhada do Yuno.

Camada pura de formatação sobre `platform/components_v2.py`. O `components_v2`
continua dono dos primitivos e do transporte HTTP; aqui só existe apresentação:
tokens de cor, estados semânticos, barra de progresso, tipografia e formatação
pt-BR.

Três regras sustentam o arquivo:

* **Sem I/O e sem domínio.** Nenhuma função recebe `guild_id`, consulta a API ou
  conhece um módulo específico. Entram dados prontos, sai string ou dict de
  componente — por isso o kit é testável sem subir bot e adotável pelos módulos
  que ainda não foram redesenhados.
* **Sem literal de cliente.** Nome de guild, cargo, prazo e produto são dado de
  configuração/ciclo e chegam por parâmetro. O kit formata, não conhece contrato.
* **Transporte fica com quem chama.** `panel()` devolve o *container*, não o
  payload, para que a escolha entre `payload()` e `meta_notice_payload()`
  (a única superfície autorizada a interpretar `@everyone`) continue explícita
  no módulo.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

from yuno_bot.platform.components_v2 import container as _container
from yuno_bot.platform.components_v2 import section as _section
from yuno_bot.platform.components_v2 import separator as _separator
from yuno_bot.platform.components_v2 import text_display as _text_display
from yuno_bot.platform.components_v2 import thumbnail as _thumbnail

# --------------------------------------------------------------------------- #
# Tokens
# --------------------------------------------------------------------------- #

BRAND = 0xFFC72C
SUCCESS = 0x57F287
WARNING = 0xF39C12
DANGER = 0xED4245
INFO = 0x5865F2
NEUTRAL = 0x95A5A6
LOCKED = 0x2B2D31

#: `text_display` aceita 4000 caracteres; os blocos são cortados em 3000 para
#: sobrar folga quando o kit acrescenta rótulo, barra ou sufixo de unidade.
TEXT_DISPLAY_LIMIT = 4000
CHUNK_LIMIT = 3000

FILLED_BLOCK = "🟩"
EMPTY_BLOCK = "⬜"

NOT_INFORMED = "Não informado"
DASH = "—"


class State(str, Enum):
    """Estados semânticos comuns aos módulos, independentes de domínio.

    Cada módulo traduz o próprio vocabulário para um destes valores e o kit
    resolve emoji e cor. É o que faz um ticket aprovado e um registro aprovado
    parecerem do mesmo produto.

    `str, Enum` em vez de `enum.StrEnum` porque o bot roda em Python 3.10 no
    servidor (e a CI valida em 3.10); `StrEnum` só existe a partir do 3.11. O
    `__str__` abaixo replica o comportamento de `StrEnum`, para que interpolar
    um estado numa string devolva o valor e não `State.RUNNING`.
    """

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    APPROVED = "approved"
    BLOCKED = "blocked"
    FAILED = "failed"
    CLOSED = "closed"
    DISABLED = "disabled"

    def __str__(self) -> str:
        return self.value


STATE_ACCENTS: dict[State, int] = {
    State.PENDING: BRAND,
    State.RUNNING: WARNING,
    State.DONE: INFO,
    State.APPROVED: SUCCESS,
    State.BLOCKED: DANGER,
    State.FAILED: DANGER,
    State.CLOSED: LOCKED,
    State.DISABLED: NEUTRAL,
}

STATE_EMOJIS: dict[State, str] = {
    State.PENDING: "⚪",
    State.RUNNING: "🟡",
    State.DONE: "🔵",
    State.APPROVED: "✅",
    State.BLOCKED: "⚠️",
    State.FAILED: "🔴",
    State.CLOSED: "⚫",
    State.DISABLED: "🚫",
}


def clip(text: str, *, limit: int = TEXT_DISPLAY_LIMIT) -> str:
    """Teto duro de um bloco de texto.

    Discord rejeita a mensagem inteira quando um `text_display` passa de 4000
    caracteres, e o dado que entra aqui é do cliente — nome de objetivo, texto
    de painel, motivo de rejeição. Cortar um rótulo é melhor do que derrubar o
    painel. Conteúdo longo por natureza deve passar por `text_blocks()`, que
    divide em vez de cortar.
    """

    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _state(value: State | str | None) -> State | None:
    if value is None:
        return None
    if isinstance(value, State):
        return value
    try:
        return State(str(value).strip().casefold())
    except ValueError:
        return None


def accent_for(state: State | str | None, *, default: int = BRAND) -> int:
    """Cor do container a partir do estado — o painel muda de cor com a situação."""

    resolved = _state(state)
    return STATE_ACCENTS[resolved] if resolved is not None else default


def state_emoji(state: State | str | None, *, default: str = "⚪") -> str:
    resolved = _state(state)
    return STATE_EMOJIS[resolved] if resolved is not None else default


def badge(state: State | str | None, label: str, *, bold: bool = False) -> str:
    """Emoji do tema + rótulo do módulo: `🟡 Em andamento`."""

    text = " ".join(str(label or "").split()) or DASH
    rendered = f"{state_emoji(state)} **{text}**" if bold else f"{state_emoji(state)} {text}"
    return clip(rendered)


# --------------------------------------------------------------------------- #
# Números e formatação pt-BR
# --------------------------------------------------------------------------- #


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    return amount if amount.is_finite() else None


def _grouped(amount: Decimal, *, places: int, fixed: bool) -> str:
    rendered = f"{amount:.{places}f}"
    integer, _, fraction = rendered.partition(".")
    negative = integer.startswith("-")
    digits = integer.lstrip("-") or "0"
    whole = f"{int(digits):,}".replace(",", ".")
    if not fixed:
        fraction = fraction.rstrip("0")
    text = f"{whole},{fraction}" if fraction else whole
    return f"-{text}" if negative else text


def number_br(
    value: Any, *, places: int = 3, fixed: bool = False, fallback: str = DASH
) -> str:
    """`1234.5` → `1.234,5`. Zeros à direita caem, a não ser com `fixed=True`."""

    amount = _decimal(value)
    if amount is None:
        return fallback
    return _grouped(amount, places=places, fixed=fixed)


def money_br(value: Any, *, places: int = 2, fallback: str = DASH) -> str:
    """`1500` → `R$ 1.500,00`."""

    amount = _decimal(value)
    if amount is None:
        return fallback
    return f"R$ {_grouped(amount, places=places, fixed=True)}"


def plural_unit(unit: Any, quantity: Any) -> str:
    value = str(unit or "unidade").strip()
    if not value:
        return "unidade"
    amount = _decimal(quantity)
    if amount == 1 or value.casefold().endswith("s"):
        return value
    plurals = {
        "unidade": "unidades",
        "caixa": "caixas",
        "pacote": "pacotes",
        "kit": "kits",
        "item": "itens",
    }
    return plurals.get(value.casefold(), value)


def quantity(value: Any, unit: Any = None, *, places: int = 3, fallback: str = DASH) -> str:
    """`1000, "unidade"` → `1.000 unidades`."""

    rendered = number_br(value, places=places, fallback=fallback)
    if rendered == fallback or unit in (None, ""):
        return rendered
    return f"{rendered} {plural_unit(unit, value)}"


def _epoch(value: Any) -> int | None:
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return int(moment.timestamp())
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def timestamp(value: Any, style: str = "f", *, fallback: str = NOT_INFORMED) -> str:
    """Marcador nativo do Discord — o membro lê no fuso dele, não no do servidor."""

    seconds = _epoch(value)
    return f"<t:{seconds}:{style}>" if seconds is not None else fallback


# --------------------------------------------------------------------------- #
# Progresso
# --------------------------------------------------------------------------- #


def percent(value: Any) -> Decimal | None:
    """Normaliza um percentual em `[0, 100]`; devolve `None` quando não dá para ler."""

    amount = _decimal(value)
    if amount is None:
        return None
    return min(max(amount, Decimal(0)), Decimal(100))


def ratio_percent(current: Any, target: Any) -> Decimal | None:
    """Percentual de `current` sobre `target`, sem estourar em meta zerada."""

    done = _decimal(current)
    goal = _decimal(target)
    if done is None or goal is None or goal <= 0:
        return None
    return percent(done / goal * 100)


def progress_bar(
    value: Any,
    *,
    length: int = 10,
    filled: str = FILLED_BLOCK,
    empty: str = EMPTY_BLOCK,
) -> str:
    """`62` → `🟩🟩🟩🟩🟩🟩⬜⬜⬜⬜`.

    O preenchimento é truncado, nunca arredondado para cima: a barra só fecha
    em 100%. Um `99,9%` que aparece completo é mentira visual — e é exatamente
    o número que alguém vai conferir.
    """

    amount = percent(value)
    if amount is None:
        amount = Decimal(0)
    blocks = int(amount * length / 100)
    blocks = min(max(blocks, 0), length)
    return filled * blocks + empty * (length - blocks)


def percent_text(value: Any, *, fallback: str = "Não calculado") -> str:
    amount = percent(value)
    if amount is None:
        return fallback
    return f"{number_br(amount, places=1)}%"


def progress_block(
    value: Any,
    *,
    label: str = "Progresso geral",
    length: int = 10,
    fallback: str = "Não calculado",
) -> str:
    """Barra + leitura numérica, o bloco que abre todo painel com meta."""

    if percent(value) is None:
        return clip(f"**📊 {label}:** {fallback}")
    return clip(f"{progress_bar(value, length=length)}\n**📊 {label}: {percent_text(value)}**")


def status_dot(value: Any, *, fallback: str = "⚪") -> str:
    """🔴 abaixo da metade, 🟡 a caminho, ✅ cumprido."""

    amount = percent(value)
    if amount is None:
        return fallback
    if amount >= 100:
        return "✅"
    if amount < 50:
        return "🔴"
    return "🟡"


def objective_row(
    name: Any,
    current: Any,
    target: Any,
    *,
    unit: Any = None,
    remaining: Any = None,
    remaining_label: str = "Restante",
    extra: str | Sequence[str] | None = None,
    places: int = 3,
    bar_length: int = 8,
) -> str:
    """Uma linha de objetivo: saúde, números, mini-barra e o que ainda falta."""

    pct = ratio_percent(current, target)
    suffix = f" {plural_unit(unit, target)}" if unit not in (None, "") else ""
    title = " ".join(str(name or "Objetivo").split()) or "Objetivo"
    lines = [
        f"{status_dot(pct)} **{title}** — "
        f"{number_br(current, places=places, fallback='0')}/"
        f"{number_br(target, places=places, fallback='0')}{suffix}"
    ]
    if pct is not None:
        lines.append(f"{progress_bar(pct, length=bar_length)} {percent_text(pct)}")
    tail: list[str] = []
    if remaining is not None:
        tail.append(
            f"{remaining_label}: "
            f"{number_br(remaining, places=places, fallback='0')}{suffix}"
        )
    if isinstance(extra, str):
        if extra.strip():
            tail.append(extra.strip())
    elif extra:
        tail.extend(item for item in extra if str(item).strip())
    if tail:
        lines.append(" · ".join(tail))
    return clip("\n".join(lines))


# --------------------------------------------------------------------------- #
# Tipografia
# --------------------------------------------------------------------------- #


def heading(title: Any, *, emoji: str | None = None, level: int = 1) -> str:
    """`# 🎫 Tickets de Farm`."""

    hashes = "#" * min(max(level, 1), 3)
    text = " ".join(str(title or "").split())
    rendered = f"{hashes} {emoji} {text}" if emoji else f"{hashes} {text}"
    return clip(rendered.rstrip())


def section_number(
    number: int, title: Any, *, emoji: str | None = None, level: int = 2
) -> str:
    """`## 📍 1 · Canais` — a numeração que dá ordem às telas de configuração."""

    hashes = "#" * min(max(level, 1), 3)
    text = " ".join(str(title or "").split())
    prefix = f"{emoji} " if emoji else ""
    return clip(f"{hashes} {prefix}{number} · {text}".rstrip())


def field(label: Any, value: Any, *, emoji: str | None = None) -> str:
    """`**👤 Membro**\\nvalor` — o campo rotulado que o embed dava de graça."""

    name = " ".join(str(label or "").split())
    title = f"{emoji} {name}".strip() if emoji else name
    body = str(value if value not in (None, "") else NOT_INFORMED)
    return clip(f"**{title}**\n{body}")


def inline_fields(
    *pairs: tuple[Any, Any] | Sequence[Any], separator: str = " · "
) -> str:
    """Recria o grid `inline` do embed: `**Lançamentos** 4 · **Recolhimentos** 1`."""

    rendered: list[str] = []
    for pair in pairs:
        if not pair:
            continue
        label, value = pair[0], pair[1] if len(pair) > 1 else None
        name = " ".join(str(label or "").split())
        if not name:
            continue
        body = str(value if value not in (None, "") else NOT_INFORMED)
        rendered.append(f"**{name}** {body}")
    return clip(separator.join(rendered))


def bullet(items: Iterable[Any], *, marker: str = "•") -> str:
    lines = [f"{marker} {item}" for item in items if str(item).strip()]
    return clip("\n".join(lines))


def history_line(text: Any, when: Any = None) -> str:
    """`• +150 Ferro — 12/08 14:32`."""

    body = " ".join(str(text or "").split())
    return clip(f"• {body} {DASH} {when}" if when not in (None, "") else f"• {body}")


NUMBER_EMOJIS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟")


def step_marker(number: int) -> str:
    return NUMBER_EMOJIS[number - 1] if 1 <= number <= len(NUMBER_EMOJIS) else f"**{number}.**"


def steps(*items: tuple[Any, Any] | Sequence[Any] | str) -> str:
    """Onboarding numerado 1️⃣2️⃣3️⃣ — o que transforma um painel em instrução."""

    blocks: list[str] = []
    for index, item in enumerate(items, start=1):
        if item in (None, ""):
            continue
        if isinstance(item, str):
            title, body = item, ""
        else:
            title = item[0] if item else ""
            body = item[1] if len(item) > 1 else ""
        title = " ".join(str(title or "").split())
        if not title and not str(body or "").strip():
            continue
        head = f"{step_marker(index)} **{title}**" if title else step_marker(index)
        blocks.append(f"{head}\n{body}".rstrip() if body else head)
    return clip("\n\n".join(blocks))


def empty_state(title: Any, hint: Any = None) -> str:
    """Estado vazio explícito: dizer que não há nada é melhor do que não dizer nada."""

    head = " ".join(str(title or "").split())
    body = str(hint or "").strip()
    return clip(f"⚠️ **{head}**\n{body}" if body else f"⚠️ **{head}**")


def medal(position: int) -> str:
    """1º ao 3º ganham medalha; do 4º em diante, `#4`."""

    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(position, f"#{position}")


def ranking_lines(rows: Iterable[tuple[Any, Any] | Sequence[Any]], *, start: int = 1) -> str:
    lines: list[str] = []
    for offset, row in enumerate(rows):
        if not row:
            continue
        name = " ".join(str(row[0] or "").split())
        value = row[1] if len(row) > 1 else None
        position = start + offset
        line = f"{medal(position)} **{name}**"
        if value not in (None, ""):
            line = f"{line} {DASH} {value}"
        lines.append(line)
    return clip("\n".join(lines))


def subtext(text: Any) -> str:
    """Rodapé nativo do Components V2 (`-#`), aplicado linha a linha."""

    body = str(text or "").strip()
    if not body:
        return ""
    return clip("\n".join(f"-# {line}".rstrip() for line in body.splitlines()))


# --------------------------------------------------------------------------- #
# Blocos e composição
# --------------------------------------------------------------------------- #


def rule(*, spacing: int = 1) -> dict[str, Any]:
    """Separador com linha."""

    return _separator(spacing=spacing, divider=True)


def space(*, spacing: int = 1) -> dict[str, Any]:
    """Respiro sem linha."""

    return _separator(spacing=spacing, divider=False)


def chunk_lines(lines: Sequence[str], *, limit: int = CHUNK_LIMIT) -> list[str]:
    """Agrupa linhas em blocos que cabem num `text_display`, sem cortar linha."""

    chunks: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n\n{line}" if current else line
        if current and len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def chunk_text(text: str, *, limit: int = CHUNK_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    return chunk_lines(text.split("\n\n"), limit=limit)


def text_blocks(text: str, *, limit: int = CHUNK_LIMIT) -> list[dict[str, Any]]:
    return [_text_display(chunk) for chunk in chunk_text(text, limit=limit)]


def avatar_section(
    *components: dict[str, Any] | str,
    avatar_url: Any = None,
    description: str | None = None,
) -> list[dict[str, Any]]:
    """Identidade com foto do membro; degrada para texto quando não há URL https."""

    rendered: list[dict[str, Any]] = []
    for item in components:
        if item in (None, ""):
            continue
        if isinstance(item, str):
            rendered.extend(text_blocks(item))
        else:
            rendered.append(item)
    if not rendered:
        return []
    url = str(avatar_url or "").strip()
    if not url.startswith("https://"):
        return rendered
    return [_section(*rendered, accessory=_thumbnail(url, description=description))]


def _expand(block: Any) -> list[dict[str, Any]]:
    if block in (None, "", ()):
        return []
    if isinstance(block, str):
        return text_blocks(block) if block.strip() else []
    if isinstance(block, dict):
        return [block]
    if isinstance(block, (list, tuple)):
        return [item for child in block for item in _expand(child)]
    return []


def panel(
    *,
    header: Any,
    blocks: Sequence[Any] = (),
    actions: Sequence[dict[str, Any]] = (),
    footer: Any = None,
    state: State | str | None = None,
    accent_color: int | None = None,
    component_id: int | None = None,
) -> dict[str, Any]:
    """Ordem canônica de layout de todo painel do Yuno.

    cabeçalho → separador → conteúdo → separador → botões → rodapé `-#`.

    Devolve o *container*; quem chama escolhe o transporte (`payload()` ou,
    só na Meta, `meta_notice_payload()`).
    """

    components: list[dict[str, Any]] = _expand(header)
    body = _expand(list(blocks))
    if components and body:
        components.append(rule())
    components.extend(body)
    rows = [row for row in actions if row]
    if components and rows:
        components.append(rule())
    components.extend(rows)
    footer_text = subtext(footer)
    if footer_text:
        if components:
            components.append(space())
        components.extend(text_blocks(footer_text))
    return _container(
        *components,
        accent_color=accent_color if accent_color is not None else accent_for(state),
        component_id=component_id,
    )
