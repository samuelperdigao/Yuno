# Mapa do Yuno

Snapshot de 2026-07-29. ~8.5k LOC. Atualize ao mudar estrutura.

## Backend — FastAPI + SQLAlchemy async

`backend/app/`

| Arquivo | LOC | O que faz |
|---|---|---|
| `main.py` | 43 | App, CORS, inclusão de routers |
| `db.py` | 48 | Engine async, `Base`, `get_session` |
| `models.py` | 246 | Todas as tabelas |
| `schemas.py` | 289 | Pydantic in/out + constante `MODULES` |
| `services.py` | 159 | Regras de negócio, `check_permission`, `audit` |
| `farm_tickets.py` | 218 | Serviço do domínio farm tickets |
| `core/config.py` | 33 | Settings via pydantic-settings |
| `core/security.py` | 46 | `require_admin_token`, sessão assinada |
| `api/auth.py` | 67 | Discord OAuth do dashboard |
| `api/config.py` | 41 | `GET/PUT /guilds/{id}/config` |
| `api/licenses.py` | 30 | Ativação de licença |
| `api/systems.py` | 95 | `SystemRecord` genérico (create/patch) |
| `api/farm_tickets.py` | 380 | Rotas do farm ticket |
| `api/internal.py` | 173 | Endpoints consumidos pelo bot (validate, check_permission) |
| `api/webhooks.py` | 32 | Webhook Mercado Pago |
| `api/products.py` | 40 | Catálogo de produtos por guild |

### Tabelas (`models.py`)

- `Customer`, `License` (key uuid4, status pending/active/blocked/revoked, `guild_id` unique)
- `GuildConfig` — **contrato central**. `admin_role_ids`, `log_channel_id`, e os JSON `modules`, `command_permissions`, `messages`, `settings`
- `SystemRecord` — registro genérico: `module`, `status`, `title`, `requester_id`, `payload` JSON. Serve qualquer módulo simples sem tabela nova
- `AuditLog`, `PaymentEvent`, `Product`
- `Ausencia` — PK composta `(guild_id, user_id)`
- `FarmTicketConfig`, `FarmWeeklyGoal`, `FarmTicket`, `FarmTicketEntry`, `FarmTicketAction`

Sem Alembic. `Base.metadata.create_all` no boot.

### Formato de `settings.discord_setup`

```json
{
  "category_ids":    {"admin": "...", "operacao": "...", "logs": "..."},
  "channel_ids":     {"set_solicitar": "...", "metas": "...", ...},
  "log_channel_ids": {"set": "...", "meta": "...", ...}
}
```

Lido por `commands/shared.py` via `channel_id_from_setup` e `log_channel_id_from_setup`.

## Bot — discord.py 2.4

`bot/yuno_bot/`

| Arquivo | LOC | O que faz |
|---|---|---|
| `main.py` | ~185 | `YunoBot`, `setup_hook` (delega ao registry), `YunoAdminCog` (`/yuno status`, `/yuno configurar`, `/yuno diagnostico`) |
| `modules.py` | ~230 | **Registry declarativo.** `ModuleSpec`, `SetupChannel`, `DashboardField`, `ModuleContext`, `discover_modules`, `load_modules` |
| `api_client.py` | ~400 | `YunoAPI` httpx. 30+ métodos, maioria de farm tickets. **Cacheia guild config** (`get_guild_config(force=)`, `cache_stats()`) |
| `cache.py` | ~100 | `TTLCache` genérico: TTL, lock por chave (anti-thundering-herd), `peek`/`set`/`invalidate`/`stats` |
| `config.py` | ~25 | `BotSettings` pydantic-settings (inclui `guild_config_cache_ttl`, default 30s) |
| `guards.py` | ~30 | `ensure_allowed(interaction, api, module, command)` → `(bool, str)`; `deny(interaction, reason)` |
| `server_setup.py` | ~230 | `SETUP_CATEGORIES`, `CORE_CHANNELS`, `PERMISSOES_NECESSARIAS`; derivadas `setup_channels()`, `log_channels()`, `module_keys()`; leitura `saved_channel_id()`/`saved_log_channel_id()`; `ensure_setup_channels(guild, config)` → `SetupResult`; `build_setup_config` |
| `diagnostics.py` | ~180 | `diagnose(guild, config, licenca_ativa)` puro → `Diagnostico`; `diagnostic_embed()` |
| `commands/shared.py` | 142 | Cores, `clean_text`, `parse_positive_int`, `make_success_embed`, `make_log_embed`, `get_guild_config`, `resolve_text_channel`, `send_module_log`, `send_to_setup_channel`, `create_record` |

### Módulos existentes

`commands/<mod>/` com `__init__.py` (declara `MODULE = ModuleSpec(...)`), `cog.py`, `embeds.py`, `modals.py`, `views.py` (nem todos têm os quatro).

Ordem canônica: set(10), meta(20), farm_tickets(25), ticket(30), parceria(40), encomenda(50), ausencia(60), radio(70), producao(80).

| Módulo | Comandos | Status |
|---|---|---|
| `set` | `/set solicitar|aprovar|reprovar|painel` | **validado** |
| `meta` | `/meta registrar` + painel | **validado** |
| `farm_tickets` | painel + controle de ticket | maior módulo (364 LOC no cog) |
| `parceria` | `/parceria cadastrar` | usa SQLite local — débito #4 |
| `ausencia` | `/setup_ausencia`, `/painel_ausencia`, `/ausencias` | |
| `ticket` | `/ticket abrir` | |
| `encomenda` | `/encomenda criar` | |
| `radio` | `/radio alterar` | |
| `producao` | `/producao registrar` | |

### Estrutura criada por `/yuno configurar`

Categorias: `Yuno - Administracao`, `Yuno - Operacao`, `Yuno - Logs`.
Canais de operação: `set-solicitar`, `set-aprovacao`, `metas-semanais`, `tickets`, `parcerias`, `encomendas`, `ausencias`, `radio`, `producao`, `yuno-logs`.
Canais de log: `logs-<modulo>` para cada um dos 9 módulos.

**Reconciliação por ID, idempotente.** Ordem: ID salvo em `settings.discord_setup` → canal de mesmo nome (adoção, migra quem configurou antes) → criação. Canal renomeado ou movido pelo cliente é respeitado: identidade é o ID.

## Dashboard

`dashboard/src/` — `App.jsx` (246), `api.js` (29), `styles.css`. Vite + React. `dist/` é build, ignore.

## Infra

`docker-compose.yml` (postgres, redis, api, bot, dashboard, caddy), `infra/Caddyfile`, `deploy.yuno.cmd` / `.ps1` (push main → Oracle → restart `yuno-api` e `yuno-bot`), `scripts/backup-postgres.sh`.

## Testes

`backend/tests/` — `test_api.py` (386), `test_bot_modal_helpers.py` (446), `test_radio.py` (91), `test_module_registry.py` (paridade bot↔backend, colisão de canal, prefixo de `command_keys`, views persistentes), `test_setup_idempotente.py` (reconciliação por ID, rename, move, adoção, diagnóstico), `test_cache.py` (TTL, isolamento entre guilds, thundering herd, erro não cacheado). 64 testes, `python -m pytest backend/tests`. Os testes do bot moram aqui por convenção do repo e ajustam `sys.path` manualmente.
