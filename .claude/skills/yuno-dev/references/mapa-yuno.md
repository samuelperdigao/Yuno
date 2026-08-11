# Mapa factual do Yuno

Snapshot de 2026-08-07. Este arquivo localiza o código atual; não define sozinho a arquitetura futura.

## Produto e processos

O Yuno é multi-tenant e vendido por licença. O bot Discord consome uma API FastAPI; o backend concentra persistência, licença, permissão e auditoria. A stack inclui PostgreSQL no desenho de produção, SQLite em desenvolvimento/instalação legada, Redis, dashboard React, Caddy e deploy no Oracle.

```text
Discord bot → API FastAPI → SQLAlchemy/Alembic → banco
dashboard web ────────────→ API
```

## Backend

Entradas principais:

| Área | Local | Responsabilidade atual |
|---|---|---|
| App | `backend/app/main.py` | FastAPI, lifespan e routers |
| Banco | `backend/app/db.py` | engine async, sessões e upgrade Alembic no boot |
| Modelos | `backend/app/models.py` | licenças, configuração, auditoria e domínios |
| Schemas | `backend/app/schemas.py` | contratos Pydantic e inventário de módulos |
| Serviços gerais | `backend/app/services.py` | configuração, permissão, licença e auditoria |
| Control Plane | `backend/app/control_plane.py` | rascunho, revisão, publicação e projeção transitória |
| API interna | `backend/app/api/internal.py` | endpoints consumidos pelo bot |
| API Control Plane | `backend/app/api/control_plane.py` | leitura, draft e publish por guild/módulo |
| Farm atual | `backend/app/farm_tickets.py` e `api/farm_tickets.py` | tickets semanais e operações existentes |
| Migrações | `backend/migrations/` | histórico Alembic versionado |

### Persistência transversal

- `License`: licença vinculada à guild.
- `GuildConfig`: configuração legada/transversal em `modules`, `command_permissions`, `messages` e `settings`.
- `ModuleConfigState`: estado atual do Control Plane com draft/publicado, revisions, atores e timestamps.
- `AuditLog`: registro de operações sensíveis.
- `SystemRecord`: registro genérico; não deve substituir domínio relacional complexo.

### API atual do Control Plane

```text
GET  /internal/control-plane/guilds/{guild_id}/modules/{module_key}
PUT  /internal/control-plane/guilds/{guild_id}/modules/{module_key}/draft
POST /internal/control-plane/guilds/{guild_id}/modules/{module_key}/publish
```

Os endpoints exigem token interno, licença ativa e ator. O contrato atual suporta revisão otimista. Somente Metas possui schema de módulo integrado.

## Bot

| Área | Local | Responsabilidade atual |
|---|---|---|
| Inicialização | `bot/yuno_bot/main.py` | carrega módulos/views e sincroniza command tree |
| Central | `bot/yuno_bot/dashboard.py` | payload Components V2, dispatch e publicação |
| Contrato transitório | `bot/yuno_bot/control_plane.py` | callbacks do módulo e autorização administrativa |
| Registry | `bot/yuno_bot/modules.py` | descoberta de 16 módulos, cogs, views e setup |
| API | `bot/yuno_bot/api_client.py` | transporte HTTP e cache de guild config |
| Setup | `bot/yuno_bot/server_setup.py` | reconciliação por IDs |
| Guardas | `bot/yuno_bot/guards.py` | licença, módulo e permissões |
| Módulos | `bot/yuno_bot/commands/<modulo>/` | runtime e interfaces existentes |

Com `CONTROL_PLANE_ENABLED=true`, a política de sync mantém somente `/yuno configurar` globalmente e no servidor de teste. Cogs antigos continuam carregados para preservar listeners e views, mas seus slash commands não são publicados.

## Módulos registrados

```text
set, meta, farm_tickets, ticket, parceria, encomenda, ausencia, radio,
producao, adv, anuncio, hierarquia, membros, acao, mod, disparo
```

Somente `meta` possui integração com o `ControlPlaneSpec` atual. Os outros módulos aparecem como migração pendente e dependem das interfaces operacionais já publicadas quando independentes de slash.

## Estado transitório que não deve ser replicado

- `ModuleSpec.dashboard_fields` descreve valores espalhados em schemas legados.
- `dashboard.module_values()` conhece formatos específicos de módulos.
- Metas usa `seed_from_legacy()` e `project_to_legacy()`.
- Publicação atual ainda projeta configuração em `GuildConfig` para o Runtime antigo.
- Comandos antigos de configuração/publicação permanecem no código, embora ocultos pela árvore reduzida.
- O setup inicial ainda parte de categorias e canais canônicos, enquanto a arquitetura nova deve permitir selecionar estrutura existente e criar nova estrutura opcionalmente.

Esses pontos são candidatos a remoção por fatia de módulo após a nova arquitetura ser validada.

## Farm atual

O domínio existente possui configurações, metas semanais, tickets, entradas e ações. A API cliente concentra muitos métodos específicos. Use essa implementação para inventariar dados e casos de borda, nunca como limite para Farm v2.

Arquivos de investigação:

- `backend/app/models.py` nas classes `Farm*`;
- `backend/app/farm_tickets.py`;
- `backend/app/api/farm_tickets.py`;
- `bot/yuno_bot/commands/farm_tickets/`;
- testes de Farm em `backend/tests/`.

## Dashboard web

`dashboard/src/` cobre ativação/licenciamento e configuração web existente. A reconstrução inicial é Discord-first; integração futura deve consumir os mesmos contratos da Central, sem criar segunda fonte de verdade.

## Infra e deploy

- `docker-compose.yml`: stack containerizada prevista.
- `deploy.yuno.ps1`: push, backup pré-deploy, atualização Oracle, restart e health.
- `scripts/backup-postgres.sh` e `restore-postgres.sh`: operação PostgreSQL.
- Ambiente Oracle atual pode operar via systemd; confirmar factual antes de qualquer deploy.

Nunca registrar tokens, chaves, IDs de cliente ou dados do ambiente vivo nesta referência.

## Testes

A suíte fica em `backend/tests/` e também cobre o bot por ajuste de `sys.path`. No snapshot atual há 113 testes, incluindo Control Plane, command tree, publicação, registry, setup idempotente e guards.

Ao alterar arquitetura, começar por `pytest -q`, depois executar testes específicos e voltar à suíte completa. Migrações devem ser exercitadas em banco vazio e em cópia representativa antes de produção.
