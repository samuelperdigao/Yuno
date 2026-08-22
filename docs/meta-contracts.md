# Contratos públicos do Sistema de Metas V2

Este documento é a fronteira suportada entre `meta` e consumidores como Tickets. Os contratos ficam em `backend/app/domain_modules/meta/contracts.py`, recebem uma `AsyncSession`, exigem `guild_id` em todas as leituras e retornam DTOs imutáveis. Nenhum contrato expõe modelos ORM, progresso ou excedente.

Quantidades de item são strings decimais com três casas conforme persistidas em `Numeric(20,3)`; dinheiro é string decimal com duas casas conforme `Numeric(20,2)`. Datas são UTC quando saem da persistência e o timezone IANA congelado do ciclo permanece em `timezone`.

## DTOs

- `GoalObjectiveSnapshot`: `objective_id`, `kind`, `name`, `unit`, `item_quantity`, `money_amount`, `position`.
- `GoalCycleSnapshot`: `cycle_id`, `goal_id`, `guild_id`, `name`, `state`, `starts_at`, `ends_at`, `timezone`, `config_version_id`.
- `ActiveGoalForMember`: `goal_id`, `cycle`, `objectives`.
- `GoalEvent`: `event_id`, `sequence`, `event_type`, `event_version`, `occurred_at`, `causation_id`, `deduplication_key`, `payload`.
- `GoalEventPage`: `events`, `next_sequence`, `has_more`.

Coleções são tuplas; `payload` é convertido recursivamente para mapeamentos somente leitura e tuplas. Os dataclasses são `frozen=True`.

## `get_active_goal_for_member`

Arquivo e assinatura:

```python
async def get_active_goal_for_member(
    session: AsyncSession, *, guild_id: str, member_id: str
) -> ActiveGoalForMember | None
```

Entrada: tenant e membro Discord em formato string. Saída: a única Meta/ciclo em que o participante está ativo e todos os objetivos congelados, ou `None` se não houver participação ativa. O índice parcial `uq_meta_active_participant` garante no banco no máximo uma resposta por membro/guild.

Ausência não é erro. Erros de conexão, transação ou schema do banco são propagados pelo SQLAlchemy; IDs de outro tenant são tratados como ausência.

Exemplo:

```python
active = await get_active_goal_for_member(
    session, guild_id="123", member_id="456"
)
if active is not None:
    ticket.meta_cycle_id = active.cycle.cycle_id
```

## `get_cycle`

Arquivo e assinatura:

```python
async def get_cycle(
    session: AsyncSession, *, guild_id: str, cycle_id: int
) -> GoalCycleSnapshot | None
```

Entrada: tenant e ID do ciclo. Saída: snapshot do ciclo, incluindo nome congelado, configuração e janela temporal, ou `None` se o ciclo não existir naquele tenant. Não retorna participantes nem objetivos.

Ausência e isolamento de tenant retornam `None`. Falhas do banco são propagadas.

Exemplo:

```python
cycle = await get_cycle(session, guild_id="123", cycle_id=91)
if cycle is None:
    raise TicketReferenceNotFound("Meta/ciclo inexistente")
```

## `get_cycle_objectives`

Arquivo e assinatura:

```python
async def get_cycle_objectives(
    session: AsyncSession, *, guild_id: str, cycle_id: int
) -> tuple[GoalObjectiveSnapshot, ...] | None
```

Entrada: tenant e ciclo. Saída: objetivos congelados ordenados por `position`. Retorna tupla vazia apenas para um ciclo existente sem objetivos; retorna `None` quando o ciclo não pertence ao tenant. O domínio normal impede criação de ciclo sem objetivos.

Falhas do banco são propagadas.

Exemplo:

```python
objectives = await get_cycle_objectives(session, guild_id="123", cycle_id=91)
if objectives is None:
    raise TicketReferenceNotFound("Meta/ciclo inexistente")
```

## `is_member_participant`

Arquivo e assinatura:

```python
async def is_member_participant(
    session: AsyncSession, *, guild_id: str, cycle_id: int, member_id: str
) -> bool
```

Entrada: tenant, ciclo e membro. Retorna `True` somente quando a linha pertence ao tenant/ciclo e ainda está ativa. Retorna `False` para ciclo ausente, outro tenant, membro nunca incluído, removido por saída ou movido por conflito. Retorno ao servidor durante o mesmo ciclo não reativa a participação.

Falhas do banco são propagadas.

Exemplo:

```python
if not await is_member_participant(
    session, guild_id="123", cycle_id=91, member_id="456"
):
    raise TicketPermissionDenied("Membro não participa deste ciclo")
```

## `read_goal_events`

Arquivo e assinatura:

```python
async def read_goal_events(
    session: AsyncSession,
    *,
    guild_id: str,
    after_sequence: int = 0,
    event_types: tuple[str, ...] = (),
    limit: int = 100,
) -> GoalEventPage
```

Entrada: tenant, cursor exclusivo, filtro opcional por tipos e limite entre 1 e 500. A saída é ordenada por `sequence`; `next_sequence` é a última sequência retornada ou o cursor recebido; `has_more` informa que há outra página para o mesmo filtro.

Erros explícitos: `ValueError` se `after_sequence < 0` ou se `limit` estiver fora de `1..500`. Falhas do banco são propagadas. Página vazia não é erro.

Exemplo:

```python
page = await read_goal_events(
    session,
    guild_id="123",
    after_sequence=checkpoint,
    event_types=("meta.goal_cycle_started.v1",),
    limit=100,
)
for event in page.events:
    await tickets.consume_meta_event(event)
checkpoint = page.next_sequence
```

## Envelope e garantias dos eventos

Todos os eventos são gravados em `meta_integration_events` na mesma transação da alteração de domínio. O envelope contém:

```json
{
  "event_id": "UUID",
  "sequence": 42,
  "event_type": "meta.goal_cycle_started.v1",
  "event_version": 1,
  "occurred_at": "2026-08-22T12:00:00Z",
  "causation_id": "discord-interaction-ou-job",
  "deduplication_key": "cycle:91:started",
  "payload": {}
}
```

`(guild_id, sequence)` e `(guild_id, deduplication_key)` são únicos. A escrita usa lock transacional por guild no PostgreSQL; retries com a mesma chave retornam o evento existente. Consumidores devem persistir `event_id` ou `(guild_id, sequence)` antes de aplicar efeitos. A ordem é definida somente dentro da guild.

### `meta.goal_cycle_started.v1`

Payload:

```json
{
  "goal_id": 12,
  "cycle_id": 91,
  "config_version_id": 4,
  "starts_at": "2026-08-22T12:00:00Z",
  "ends_at": "2026-08-23T00:00:00Z",
  "participant_ids": ["456", "789"]
}
```

Emitido quando o aviso foi localizado/publicado e a ativação transacional do ciclo terminou. Chave: `cycle:{cycle_id}:started`.

### `meta.goal_cycle_ended.v1`

Payload de encerramento normal:

```json
{"goal_id": 12, "cycle_id": 91, "reason": "COMPLETED"}
```

No encerramento definitivo por substituição total inclui também `"recurrence_disabled": true` e `reason` igual a `REPLACED`. É emitido na transação que encerra o ciclo; a recorrência só é desabilitada de forma permanente nesse caso. Chaves: `cycle:{cycle_id}:ended:completed` ou `cycle:{cycle_id}:ended:replaced`.

### `meta.participant_removed_from_cycle.v1`

Payload por saída:

```json
{"goal_id": 12, "cycle_id": 91, "member_id": "456", "reason": "LEFT_GUILD"}
```

Por conflito inclui `reason` igual a `MOVED_TO_ANOTHER_GOAL` e `destination_goal_id`. É emitido quando o participante ativo deixa o ciclo; não há evento de reentrada automática. Chave por saída: `cycle:{cycle_id}:member:{member_id}:left`; por conflito: `cycle:{cycle_id}:member:{member_id}:removed:goal:{destination_goal_id}`.

### `meta.participant_moved_to_another_goal.v1`

Payload:

```json
{
  "member_id": "456",
  "source_goal_id": 12,
  "source_cycle_id": 91,
  "destination_goal_id": 13,
  "destination_cycle_id": 92
}
```

Emitido junto da remoção correlacionada, na mesma transação de ativação da Meta mais nova. Ambos compartilham `causation_id`. Chave: `member:{member_id}:moved:{source_cycle_id}:{destination_cycle_id}`.

## Handoff para Tickets

Tickets deve depender somente deste arquivo. Não importe `models.py`, `services.py`, `farm.*` ou objetos ORM de Metas.

Fluxo recomendado para abrir um ticket:

1. Chamar `get_active_goal_for_member` na mesma transação da reserva do ticket.
2. Copiar para o ticket o `cycle_id`, `goal_id`, a janela temporal e os objetivos retornados; o snapshot do ticket continua válido mesmo após o ciclo terminar.
3. Para reabrir ou autorizar ação em ticket existente, usar o snapshot persistido do ticket. Use `is_member_participant` apenas quando a regra exigir participação ainda ativa.
4. Consumir `read_goal_events` com cursor por guild para projeções e automações; deduplicar antes de efeitos externos.
5. Tratar `None`/`False` como ausência de vínculo elegível, nunca como erro 500.

O novo Metas não armazena progresso. Entradas, comprovantes, cálculos, excedentes e estado de entrega pertencem a Tickets. Tickets já persistidos no legado permanecem legíveis/finalizáveis, mas a abertura/reserva baseada em `FarmWeeklyGoal` foi removida e não deve ser reintroduzida.
