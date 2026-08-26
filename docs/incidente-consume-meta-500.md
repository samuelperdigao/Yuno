# Incidente — `meta-events/consume` devolvendo 500 a cada boot (resolvido)

> Diagnosticado e corrigido em 2026-08-26. Correção ainda **não implantada** no
> servidor de teste no momento em que este documento foi escrito.

## Sintoma

`POST /internal/platform/guilds/{guild}/modules/farm_tickets/meta-events/consume`
retornava 500 em toda subida do bot, desde 2026-08-22. O cursor de eventos da
Meta (`farm_ticket_v2_meta_cursors`) ficou congelado em `last_sequence = 1`
enquanto `meta_integration_events` acumulava até a sequência 11 — ou seja,
**nenhum fim de ciclo, remoção ou troca de participante chegou ao Tickets de
Farm por quatro dias**.

## Causa raiz

`freeze_and_close_for_cycle` agenda a limpeza terminal com
`correlation_id = f"meta:{event_id}:ticket:{ticket_id}"`. Esse formato tem
**85 caracteres fixos** (5 + 36 + 8 + 36) e a coluna era `VARCHAR(80)`:

```
asyncpg.exceptions.StringDataRightTruncationError:
value too long for type character varying(80)
INSERT INTO automation_tasks (...)
```

Não é dado corrompido nem específico daquela guild: **todo fim de ciclo que
precise agendar limpeza de ticket quebra**, em qualquer servidor.

### Por que 248 testes não pegaram

O SQLite **ignora o tamanho declarado de `VARCHAR(n)`** e grava 85 caracteres
numa coluna de 80 sem reclamar; o PostgreSQL recusa. A suíte roda em SQLite.
É a mesma família do bug do `enum.StrEnum`, em que o venv local (3.12) escondia
o que o servidor (3.10) não aceitava: **o ambiente de teste é mais permissivo
que o de produção, e a diferença vira 500 só depois do deploy.**

### Por que ficou quatro dias sem diagnóstico

`migrations/env.py` chamava `fileConfig(config.config_file_name)` sem
`disable_existing_loggers=False`. Como `create_database()` roda o Alembic dentro
do lifespan do FastAPI — depois de o uvicorn já ter criado seus loggers — esse
`fileConfig` **desligava `uvicorn.error`, `uvicorn.access` e os loggers das
libs**. O `uvicorn.error` é justamente por onde sai o
`Exception in ASGI application` com o traceback de todo 500.

Resultado: o journal do `yuno-api` mostrava as linhas do Alembic e depois nada —
nem access log, nem "Application startup complete", nem traceback. **Toda a API
estava cega para erro de servidor em produção.**

## Hipótese anterior, descartada

Uma investigação anterior apontou o `.scalar_one()` de
`services.py` (busca do `FarmTicketCycle`) levantando `NoResultFound` por ticket
sem snapshot de ciclo. A query no banco de produção descartou isso:

```sql
select t.id from farm_ticket_v2_tickets t
left join farm_ticket_v2_cycles c on c.ticket_id = t.id
where c.id is null;
-- 0 linhas (2 tickets, 2 ciclos)
```

O `.scalar_one()` continua sendo um ponto frágil, mas não é o que causou este
incidente.

## Correção

| O quê | Onde |
|---|---|
| `correlation_id` de `VARCHAR(80)` para `VARCHAR(160)` nas 7 tabelas que o têm | migração `a9b0c1d2e3f4` |
| Constante única `CORRELATION_ID_MAX_LENGTH` + `clamp_correlation_id()` | `app/platform/correlation.py` |
| Remoção dos 5 remendos `[:80]` espalhados por `farm_tickets/services.py` | eram sintoma, truncavam UUID no meio |
| `fileConfig(..., disable_existing_loggers=False)` | `migrations/env.py` |

### Barreiras para a classe inteira do bug

- **`backend/tests/conftest.py`**: listener global em `Session.before_flush` que
  recusa qualquer string maior que o `VARCHAR(n)` declarado. Faz a suíte inteira
  em SQLite cobrar a semântica do PostgreSQL, sem que os arquivos de teste
  precisem saber que ele existe. Foi ele que apontou, de imediato, que
  `_begin()` gerava `interaction_id` de 53 caracteres para uma coluna de 32 —
  fixture irreal, já que em produção o valor é um snowflake do Discord e o
  schema corta em `max_length=32`.
- **`backend/tests/test_api_logging.py`**: roda o boot num subprocesso limpo e
  falha se o Alembic desligar `uvicorn.error`.
- **`backend/tests/test_correlation_id.py`**: trava o tamanho canônico em todas
  as tabelas e o formato de 85 caracteres do fim de ciclo.

Suíte após a correção: **249 passed, 6 skipped**.

## Pendente

1. **Deploy da correção** — inclui `alembic upgrade head` (a migração
   `a9b0c1d2e3f4` é necessária; sem ela o 500 continua).
2. **Destravar o cursor**: depois do deploy, o próximo boot do bot processa as
   sequências 2 a 11 de uma vez. Conferir que `last_sequence` chega a 11 e que
   os tickets dos ciclos 1–3 fecham como esperado.
3. **Suítes reais** (`test_platform_postgres.py`, `test_farm_tickets_minio.py`)
   continuam sem execução — são elas que pegariam esta classe de bug antes do
   deploy, e são o único lugar onde `VARCHAR` é cobrado de verdade.
4. `docs/deployment.md` descreve uma stack Docker Compose, mas o servidor de
   teste roda `systemd` + venv (`yuno-api.service`, `yuno-bot.service`). O
   documento está desatualizado em relação à máquina real.
