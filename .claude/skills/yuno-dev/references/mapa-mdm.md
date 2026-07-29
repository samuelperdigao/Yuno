# Mapa do Morro do Mineiro Bot

Snapshot de 2026-07-29. ~22k LOC. **Fonte de features validadas, nunca destino de código novo.**

Caminho: `C:\Users\sperd\OneDrive\Projetos\Morro do Mineiro Bot`

## Arquitetura

Monólito discord.py + SQLite local. Sem API, sem multi-tenant real (tem `guild_id` nas tabelas, mas roda num servidor só).

```
main.py              MyBot, setup_hook carrega COG_EXTENSIONS, sync global
core/config.py       TOKEN, APPLICATION_ID, DB_PATH, TZ. Alguns IDs legados hardcoded
core/extensions.py   tupla COG_EXTENSIONS (31 cogs)
core/permissions.py  has_approver_permission, is_lideranca, is_permitido_farm
core/command_config.py  lê data/commands_config.json com cache por mtime
core/discord_helpers.py fetch_channel_safe, respond_ephemeral
core/date_utils.py   semana ISO, formato BR
core/role_sync.py, role_promotion.py, farm_policy.py
services/db_schema.py   SCHEMA_SQL + migrações (518)
services/db_service.py  **2556 LOC — god module**, todo acesso a dados
services/set_service.py, lideranca_service.py, paineis_service.py, log_service.py
config/paineis.py    definição declarativa dos painéis
data/                farm.db, autoroles_config.json, commands_config.json
```

`services/log_service.py:send_log(bot, guild, sistema, embed, ...)` resolve o canal via `system_config` — mesma ideia do `send_module_log` do Yuno.

### Config por guild

Duas tabelas:

- `guild_config` — **colunas fixas, ~24 e crescendo** a cada feature (`approval_channel_id`, `cargos_lideranca_farm`, `flanelinha_role_id`, `parceria_category_id`...). É exatamente o antipadrão que o `settings` JSON do Yuno evita.
- `system_config` — `(guild_id, sistema)` → `canal_interacao_id`, `canal_log_id`. Genérico, bom padrão.

## Cogs por tamanho

| Cog | LOC | O que é | Portar? |
|---|---|---|---|
| `farm.py` | 1707 | Metas semanais, lançamentos, aprovação, ranking, histórico | Fase 2 — itens hardcoded |
| `farm_tickets.py` | 1571 | Tickets privados de farm | Já existe no Yuno |
| `farm_advertencias.py` | 1164 | Advertência automática por meta não cumprida | Fase 2 |
| `bau.py` + `bau_core.py` + `bau_gerentes.py` | 2370 | Baú da gerência, estoque, slots | **Não** — específico da facção |
| `recolhimento.py` | 1093 | Ciclo semanal de recolhimento de dinheiro/farm | **Não** — específico |
| `acao.py` + `acao_painel.py` | 1223 (metade de `acao.py` era código morto duplicado, nunca importado) | Sistema de ações/missões (fuga, tiro) | Já existe no Yuno (`commands/acao/`, catálogo de missões configurável por servidor, participantes em `SystemRecord`) |
| `dashboard.py` | 874 | **Painel de configuração Components V2 dentro do Discord** | **Sim — prioridade máxima** |
| `setup.py` | 683 | `/setup_bot`, `/setup_farm`, `/setup_ausencia` | Conceito, não código |
| `parcerias.py` | 674 | Registro de parcerias | Já existe no Yuno (com débito) |
| `farm_painel.py` | 603 | Painel fixo de farm | Fase 2 |
| `colete.py` | 565 | Fabricação de coletes com custo de materiais | **Não** — específico |
| `disparo.py` | 545 | Disparo de mensagem em canais privados em massa | Já existe no Yuno (`commands/disparo/`, alvo é `farm_tickets.folders_category_id`, sem JSON local) |
| `farm_relatorio.py` | 505 | Relatório de pendentes da semana | Fase 2 |
| `set_views.py` | 363 | SetModal, ApprovalView, SetPanelView, rate-limit | Já validado no Yuno |
| `paineis.py` | 379 | Listeners e handlers dos painéis | Conceito |
| `hierarquia.py` | 335 | Painel de gestão de hierarquia de cargos | Já existe no Yuno (`commands/hierarquia/`, escada configurável por ID, não nome) |
| `anuncio.py` | 335 | Sistema de anúncios com cargos anunciantes | Já existe no Yuno (`commands/anuncio/`, cargos via `command_permissions`) |
| `adv.py` | 309 | Advertências manuais (painel + modal + dias) | Já existe no Yuno (`commands/adv/`, via `SystemRecord`, sem tabela própria) |
| `lideranca.py` | 308 | Handlers do painel de liderança | Avaliar |
| `ranking_painel.py` | 294 | Ranking semanal público | Fase 2 |
| `encomenda.py` | 269 | Encomendas | Já existe no Yuno |
| `radio.py` | 261 | Definição de rádio | Já existe no Yuno |
| `ausencia.py` | 260 | Ausências multi-server | Já existe no Yuno |
| `mod.py` | 252 | `/clear`, `/organizar_canais` | Já existe no Yuno (`commands/mod/`, `/mod limpar` e `/mod organizar_canais`) |
| `farm_embeds.py` | 222 | Builders de embed do farm | Fase 2 |
| `membros.py` | 190 | Eventos join/leave, reconciliação de pastas | Já existe no Yuno (`commands/membros/`, libera pasta de farm ao sair) |
| `sistema.py` | 67 | `/ping`, `/status` | Yuno já tem `/yuno status` |

## O padrão que vale copiar: `cogs/dashboard.py`

Painel único de configuração dentro do Discord usando Components V2 crus (payload manual, sem wrapper do discord.py):

```python
_ACTION_ROW = 1; _BUTTON = 2; _SECTION = 9
_TEXT = 10; _SEPARATOR = 14; _CONTAINER = 17
_FLAG_V2 = 1 << 15   # IS_COMPONENTS_V2
```

Lista `SISTEMAS` declarativa (`key`, `icon`, `nome`, `desc`), paginada em duas páginas, cada sistema com botão `≡` de `custom_id` `dashboard:config_<key>`. Sistemas com campos extras têm modal especializado (set, farm, anuncio); o resto usa modal genérico de `canal_interacao` + `canal_log`.

**Ao portar para o Yuno:** manter a ideia (lista declarativa + paginação + modal por sistema), mas gerar a lista a partir do registry de módulos e persistir via `PUT /guilds/{id}/config`, não via SQLite. `DASHBOARD_CHANNEL_ID` hardcoded tem que sair.

## Específico do Morro do Mineiro (precisa virar configuração ao portar)

- Itens de farm: `folha`, `opio`, `seringa`, `agulha` — colunas literais em `metas`, `progresso`, `eventos`
- Materiais de colete: ferro, plástico, tecido, alumínio, borracha
- Nomes de cargo: `| 01 Dono`, `| 02`, `| 03`, `| Gerente de Produção`, `| Gerente de Produtos`, `Flanelinha`
- IDs hardcoded: `DASHBOARD_CHANNEL_ID`, `CANAL_LOG_ENTRADA_ID`, `CANAL_LOG_PD_ID`
- Fuso `America/Sao_Paulo` fixo
- Conceito de "dinheiro sujo/limpo", semana fechando domingo 23:59

## Testes

`tests/` — 17 arquivos pytest. `test_bau_core`, `test_farm_*`, `test_role_*`, `test_date_utils`. Bom sinal de maturidade; use-os como especificação ao portar.
