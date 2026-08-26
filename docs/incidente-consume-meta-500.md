# Incidente — `meta-events/consume` devolvendo 500 a cada boot (resolvido)

> Diagnosticado, corrigido e **implantado** no servidor de teste em 2026-08-26
> (`0ad8c00`, `2f55b0f`, `12c8985`). Cursor destravado e verificado em produção.

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

## Segunda metade: a coluna não bastava (`2f55b0f`)

Alargar só a coluna deixou o bug vivo em outro ponto. Depois do primeiro deploy
o fim de ciclo finalmente **foi agendado** — e aí todo job de limpeza terminal
passou a levar **422 no `POST .../farm_tickets/bindings`**, porque o contrato de
transporte continuava estreito:

```python
ActorContextIn.correlation_id: str = Field(min_length=1, max_length=80)
```

A correlação de 85 caracteres passou a ser aceita pelo banco e seguiu recusada
pelo Pydantic, antes de chegar ao domínio. Confirmado separando as camadas
contra o banco de produção, em transação com rollback: `upsert_discord_binding`
aceita o payload; quem recusa é o schema.

Corrigido em `ActorContextIn`, `WorkItemScheduleIn`, `DeliveryScheduleIn`,
`InteractionBeginIn` e no `CorrelationHeader`, todos passando a usar
`CORRELATION_ID_MAX_LENGTH`. `test_schema_de_transporte_acompanha_a_coluna`
varre os schemas de entrada e o header e falha se algum capar abaixo da coluna.

**Lição:** um limite de tamanho vive em duas camadas. Mudar uma sem a outra
troca um erro por outro.

## Terceira correção: `last_error` inútil (`12c8985`)

Os cinco jobs falhos gravavam `"Falha no handler do job."` — o coordinator
descartava a exceção. O traceback ia para o journal do bot, mas quem consulta
`automation_tasks`, que é por onde se descobre que a fila travou, via só a frase
genérica. `describe_error()` agora grava tipo, mensagem e, em erro HTTP, o corpo
da resposta — é nele que o FastAPI diz qual campo recusou.

## Verificação em produção

- `meta-events/consume` → **200 OK** (era 500).
- Cursor: `last_sequence = 11`, `bootstrap_complete = true`. As 11 sequências
  represadas processaram de uma vez, com 11 receipts gravados.
- Ticket do ciclo 1 fechou como `FINALIZED_INCOMPLETE` / `CYCLE_ENDED`, binding
  liberado. Ticket do ciclo 4 segue `APPROVED` e ativo.
- `farm_tickets.provision` e `farm_tickets.storage.cleanup`, que estavam em
  retry com 422, concluíram.
- Fila: 76 `succeeded`, 3 `failed`, 1 `pending`, 1 `cancelled`. As 3 falhas são
  anteriores às correções e estão exauridas; as duas provas do banco estão
  íntegras (`STORED` e `DELETED`, ambas com entrega na thread confirmada), então
  não houve dano funcional.
- Journal do `yuno-api`: **zero** `500 Internal` ou `Exception in ASGI`, e o
  access log voltou a aparecer.

## Pendente

1. **Suítes reais** (`test_platform_postgres.py`, `test_farm_tickets_minio.py`)
   continuam sem execução — são o único lugar onde `VARCHAR` é cobrado de
   verdade antes do deploy.
2. **T-01 a T-07** de `docs/tickets-v2-acceptance.md` continuam pendentes:
   exigem interação real no Discord.
3. Três tarefas em `failed` de 22 e 26/08 seguem na fila como resíduo. Uma delas
   (`farm_tickets.proof.process`) está com `attempts = 15` contra
   `max_attempts = 10` — vale entender como um job ultrapassou o próprio limite.
4. `docs/deployment.md` descreve uma stack Docker Compose, mas o servidor de
   teste roda `systemd` + venv (`yuno-api.service`, `yuno-bot.service`). O
   documento está desatualizado em relação à máquina real.
