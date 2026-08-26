# Kit de UI do Yuno — guia de estilo

`bot/yuno_bot/platform/ui_kit.py` é a linguagem visual compartilhada do produto.
Todo painel, embed e mensagem que o cliente vê deve sair dele.

O problema que ele resolve: cada módulo escrevia o próprio texto do zero. O
resultado era um bot que parecia quatro bots — container sempre amarelo
independente do estado, sem barra de progresso, sem rótulo com emoji, com
"Configuracoes" sem cedilha num produto pt-BR vendido por licença. O Morro do
Mineiro, um monólito SQLite de uma guild só, entregava painel melhor acabado
que o Yuno. Este kit inverte isso.

---

## 1. Onde o kit entra

```
components_v2.py   primitivos + transporte HTTP   (não mudou)
      ↑
   ui_kit.py       tokens, tipografia, formatação  ← você escreve aqui
      ↑
domain_modules/*   conteúdo e domínio
```

Três regras que sustentam o arquivo:

1. **Sem I/O e sem domínio.** Nenhuma função recebe `guild_id`, consulta API ou
   conhece um módulo. Entram dados prontos, sai string ou dict de componente.
2. **Sem literal de cliente.** Nome de guild, cargo, prazo e produto são dado de
   configuração/ciclo e chegam por parâmetro.
3. **O transporte fica com quem chama.** `panel()` devolve o *container*; o
   módulo escolhe entre `payload()` e `meta_notice_payload()` — que é a única
   superfície autorizada a interpretar `@everyone`.

---

## 2. Tokens de cor

| Token | Hex | Quando |
|---|---|---|
| `BRAND` | `0xFFC72C` | Amarelo Yuno. Estado neutro, tela de configuração. |
| `SUCCESS` | `0x57F287` | Aprovado, publicado, no ar. |
| `WARNING` | `0xF39C12` | Em andamento, pausado. |
| `DANGER` | `0xED4245` | Rejeitado, bloqueado, falhou, ação destrutiva. |
| `INFO` | `0x5865F2` | Encerrado com sucesso (ciclo terminou). |
| `NEUTRAL` | `0x95A5A6` | Desligado por escolha do cliente. |
| `LOCKED` | `0x2B2D31` | Encerrado manualmente, arquivado. |

**Nunca escreva um hex no módulo.** `diagnostics.py` importa `SUCCESS/WARNING/
DANGER` daqui em vez de manter o próprio verde — é o que garante que o verde do
Yuno seja um verde só.

---

## 3. Estados semânticos

Cada módulo traduz o próprio vocabulário para um `State`, e o kit resolve emoji
e cor. É isso que faz um ticket aprovado e um registro aprovado parecerem do
mesmo produto.

| `State` | Emoji | Cor | Leitura |
|---|---|---|---|
| `PENDING` | ⚪ | `BRAND` | Ainda não começou / aguardando você |
| `RUNNING` | 🟡 | `WARNING` | Em andamento |
| `DONE` | 🔵 | `INFO` | Encerrado, ciclo completo |
| `APPROVED` | ✅ | `SUCCESS` | Aprovado / no ar |
| `BLOCKED` | ⚠️ | `DANGER` | Impedido por uma condição |
| `FAILED` | 🔴 | `DANGER` | Rejeitado / terminou incompleto |
| `CLOSED` | ⚫ | `LOCKED` | Encerrado manualmente |
| `DISABLED` | 🚫 | `NEUTRAL` | Desligado |

O módulo declara a tradução numa tabela no topo do arquivo:

```python
TICKET_STATES: dict[str, tuple[uk.State, str]] = {
    "IN_PROGRESS": (uk.State.RUNNING, "Em andamento"),
    "APPROVED": (uk.State.APPROVED, "Aprovado"),
    "FINALIZED_INCOMPLETE": (uk.State.FAILED, "Finalizado incompleto"),
    "CLOSED_MANUALLY": (uk.State.CLOSED, "Encerrado manualmente"),
}
```

E usa em dois lugares — o selo e a cor do container:

```python
state, label = TICKET_STATES[status]
uk.panel(..., state=state)          # accent_color sai daqui
uk.badge(state, label)              # "🟡 Em andamento"
```

---

## 4. Ordem canônica de layout

`panel()` fixa a ordem que dá a sensação de "tudo do mesmo bot":

```
cabeçalho
──────────────  separador
identidade (com avatar, quando houver)
dados
──────────────  separador (passado em blocks via uk.rule())
progresso e objetivos
──────────────  separador
botões
-# rodapé com a regra do sistema
```

```python
payload(
    uk.panel(
        header=uk.heading("Ticket de Farm · Ana", emoji="🎫"),
        blocks=[
            uk.avatar_section(identidade, avatar_url=url, description="Foto do membro"),
            dados,
            uk.rule(),
            uk.progress_block(progresso),
            uk.field("Objetivos", objetivos, emoji="📦"),
        ],
        actions=rows,
        footer="Este ticket segue o ciclo da Meta e encerra <t:...:R>.",
        state=state,
    )
)
```

`blocks` aceita `str`, dict de componente, lista aninhada e `None`. String vazia
e `None` somem — não vira separador solto. String longa demais é fatiada em
vários `text_display` automaticamente.

---

## 5. Catálogo

### Progresso

```python
uk.progress_bar(62)            # 🟩🟩🟩🟩🟩🟩⬜⬜⬜⬜
uk.progress_block("35.500")    # barra + "**📊 Progresso geral: 35,5%**"
uk.status_dot(49)              # 🔴  (<50)   🟡 (<100)   ✅ (=100)
uk.objective_row("Ferro", "620", "1000", unit="unidade", remaining="380",
                 extra=("Recolhido: 200 unidades",))
# 🟡 **Ferro** — 620/1.000 unidades
# 🟩🟩🟩🟩⬜⬜⬜⬜ 62%
# Restante: 380 unidades · Recolhido: 200 unidades
```

O preenchimento da barra **trunca, nunca arredonda para cima**: a barra só fecha
em 100%. Um `99,9%` que aparece completo é mentira visual — e é exatamente o
número que a liderança confere.

`objective_row` exige o par atual/alvo. Onde só existe o alvo (o aviso de ciclo
da Meta, o editor antes de qualquer lançamento) use uma linha simples com
`uk.bullet` — uma barra ali mostraria um `0%` que não significa nada.

### Tipografia

```python
uk.heading("Tickets de Farm", emoji="🎫")      # "# 🎫 Tickets de Farm"
uk.heading("Resultado", level=3)               # "### Resultado"
uk.section_number(1, "Canais", emoji="📍")     # "## 📍 1 · Canais"
uk.field("Membro", "<@1>", emoji="👤")         # "**👤 Membro**\n<@1>"
uk.inline_fields(("Lançamentos", 4), ("Recolhimentos", 1))
                                               # "**Lançamentos** 4 · **Recolhimentos** 1"
uk.bullet(["a", "b"])                          # "• a\n• b"
uk.history_line("+150 Ferro", "12/08 14:32")   # "• +150 Ferro — 12/08 14:32"
uk.steps(("Preencha o ID", "Use o ID do jogo."), ("Aguarde", "A equipe analisa."))
                                               # 1️⃣ **…**  /  2️⃣ **…**
uk.empty_state("Sem meta definida", "A liderança ainda não definiu.")
uk.medal(1)  uk.ranking_lines([("Ana", "1.234")])
uk.subtext("Regra do sistema")                 # "-# Regra do sistema"
```

`section_number` é a numeração que dá ordem às telas de configuração — o mesmo
`## 📍 1 · Canais` em Registro, Tickets e Metas.

`steps` é o onboarding do painel de set do Morro do Mineiro. **Não invente
passos**: em `registration` e `farm_tickets` a numeração só aparece quando o
cliente escreveu mais de uma linha de instrução na Central. Uma frase única
continua uma frase única.

### pt-BR

```python
uk.money_br(1500)                  # "R$ 1.500,00"
uk.number_br("100000.000")         # "100.000"
uk.quantity(1000, "unidade")       # "1.000 unidades"  (1 → "1 unidade")
uk.timestamp(valor, "f")           # "<t:1787972400:f>"
uk.timestamp(valor, "R")           # "<t:1787972400:R>"  ("em 5 dias")
```

Todos devolvem um fallback (`—`, `Não informado`) em vez de estourar quando o
dado não vem. Prefira `timestamp` a formatar data na mão: o membro lê no fuso
dele. A exceção é a janela oficial do ciclo da Meta, que é impressa no fuso
configurado no ciclo porque é o horário de operação do servidor.

### Limites

`text_display` aceita 4000 caracteres e o Discord recusa a **mensagem inteira**
quando um bloco passa disso. Duas defesas:

* `uk.clip(texto)` — teto duro, aplicado por dentro de todo helper de uma linha.
  Cortar um rótulo é melhor do que derrubar o painel.
* `uk.chunk_lines(linhas)` / `uk.text_blocks(texto)` — divide em vez de cortar,
  para conteúdo longo por natureza (lista de objetivos, histórico).

`farm_tickets._chunk_lines` delega para `uk.chunk_lines`: um teto só, no kit.

---

## 6. Antes e depois

Painel privado do ticket, antes:

```
# Ticket de Farm · Ana
**Membro**
<@100> · Ana | 10 · ID `10`
**Meta e ciclo**
Meta semanal
<t:…:f> → <t:…:f>
**Estado**
🟡 Em andamento
**Progresso geral**
62.000%
**Objetivos**
**Ferro** — 620.000/1000.000 unidade
Restante da Meta: 380.000 unidade · Recolhido: 200.000 unidade · Saldo: 420.000 unidade
```
Container sempre `0xFFC72C`, sem barra, número cru, unidade no singular.

Depois:

```
# 🎫 Ticket de Farm · Ana
──────────────
[avatar]  **👤 Membro**
          <@100> · Ana | 10

          **🎮 ID do Jogo**
          `10`

**🎯 Meta e ciclo**
Meta semanal

**📅 Período**
<t:…:f> → <t:…:f>
Encerra <t:…:R>

**📌 Status**
🟡 Em andamento
──────────────
🟩🟩🟩🟩🟩🟩⬜⬜⬜⬜
**📊 Progresso geral: 62%**

**📦 Objetivos**
🟡 **Ferro** — 620/1.000 unidades
🟩🟩🟩🟩🟩⬜⬜⬜ 62%
Restante da Meta: 380 unidades · Recolhido: 200 unidades · Saldo: 420 unidades
──────────────
[ botões ]
-# Este ticket segue o ciclo da Meta e encerra <t:…:R>.
```
Container laranja porque está em andamento; verde quando aprovado; vermelho
quando finalizado incompleto; preto quando encerrado à mão.

---

## 7. Adotando o kit num módulo que ainda não migrou

1. `from yuno_bot.platform import ui_kit as uk` e troque `COLOR = 0x…` por
   `COLOR = uk.BRAND`.
2. Declare a tabela `MODULE_STATES` traduzindo o vocabulário do domínio para
   `uk.State`.
3. Troque `container(...)` por `uk.panel(...)` e passe `state=`.
4. Troque texto solto por `heading`/`field`/`inline_fields`/`section_number`.
5. Rodapé com a regra do sistema em `subtext` — **derivado de config/ciclo**,
   nunca prazo, cargo ou nome de guild literal.
6. Números e datas por `money_br`/`number_br`/`quantity`/`timestamp`.
7. Rode `backend/tests/test_ui_kit.py` e os testes do módulo.

### O que nunca entra no kit

Nome de guild, "liderança", "domingo às 23:59", produto, cargo e prazo fixo.
Tudo isso é dado de config/ciclo e chega por parâmetro. O kit formata; não
conhece contrato.

---

## 8. Estado da migração

| Módulo | Situação |
|---|---|
| `platform/ui_kit.py` | fonte da verdade |
| `dashboard.py` (Central) | migrado |
| `domain_modules/farm_tickets` | migrado (`ui.py`, `admin.py`) |
| `domain_modules/meta` | migrado (`ui.py`) |
| `domain_modules/registration` | migrado (`ui.py`, `renderers.py`) |
| `domain_modules/tags` | migrado (`ui.py`) |
| `diagnostics.py` | importa os tokens |
| `commands/*` | legado aposentado (`retired=True`), fora da Central |
