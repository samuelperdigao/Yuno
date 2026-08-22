# Tickets de Farm V2 — matriz de aceite

Esta matriz liga os 56 cenarios obrigatorios aos testes automatizados e ao
roteiro de validacao no Discord de teste. Nenhuma linha desta matriz autoriza
deploy em producao.

## Invariantes de encerramento e comprovante

- Aprovacao, finalizacao e exclusao nunca cancelam uma operacao ativa. Essas
  acoes permanecem bloqueadas ate confirmacao, expiracao natural ou falha
  tecnica definitiva registrada.
- O deadline de cinco minutos qualifica `received_at`. Depois do claim atomico,
  download, validacao profunda e S3 podem continuar ou repetir depois do prazo.
- Fim de ciclo e nova Meta congelam os totais reais. Nenhum recolhimento,
  allocation ou ajuste sintetico e criado para zerar saldo.
- `status` registra o resultado historico; `last_resource_removal_reason` e os
  eventos de binding registram o lifecycle Discord sem substituir `APPROVED`
  ou `FINALIZED_INCOMPLETE`.

## Matriz 1–56

| # | Cenario | Evidencia automatizada principal |
|---:|---|---|
| 1 | Abertura normal | `test_open_ticket_uses_public_contract_snapshots_and_is_idempotent` |
| 2 | Membro sem Registro | `test_open_ticket_uses_public_contract_snapshots_and_is_idempotent` |
| 3 | Membro sem Meta | `test_open_ticket_uses_public_contract_snapshots_and_is_idempotent` |
| 4 | Ticket duplicado | teste de abertura acima e `test_postgres_farm_tickets_serializes_open_operations_fifo_and_admin_races` |
| 5 | Abertura por administrador | teste de abertura idempotente com segundo ator e roteiro Discord T-01 |
| 6 | Permissoes | `test_ticket_operations_distinguish_owner_discord_admin_and_manage_guild` |
| 7 | Mudanca de cargo admin | `test_published_ticket_admin_roles_must_move_all_operational_grants_together` e roteiro Discord T-02 |
| 8 | Lancamento simples | `test_streamed_image_is_stored_before_entry_confirmation` |
| 9 | Multi-item | `test_multi_item_and_money_entry_and_withdrawal_keep_numeric_precision` |
| 10 | Dinheiro no lancamento | teste multi-item/dinheiro acima |
| 11 | Modal multi-etapa | `test_multi_step_form_preserves_draft_and_starts_deadline_only_after_last_step` |
| 12 | Comprovante valido | `test_streamed_image_is_stored_before_entry_confirmation` e teste MinIO real |
| 13 | Comprovante por autor errado | `test_only_one_operation_and_only_author_can_claim_persisted_deadline` |
| 14 | Arquivo nao imagem | `test_deeply_invalid_image_releases_claim_without_resetting_deadline` |
| 15 | Timeout | `test_only_one_operation_and_only_author_can_claim_persisted_deadline` |
| 16 | Restart durante timeout | `test_timeout_deadline_and_job_survive_session_restart` |
| 17 | Lancamento duplicado | idempotencia/operacao unica nos testes local e PostgreSQL |
| 18 | Edicao valida | `test_valid_edit_requires_new_proof_and_can_auto_approve` |
| 19 | Edicao sem novo comprovante | `test_edit_is_append_only_expires_to_original_and_allocation_blocks_it` |
| 20 | Timeout de edicao | mesmo teste append-only acima |
| 21 | Bloqueio de edicao apos recolhimento | mesmo teste append-only acima |
| 22 | Recolhimento parcial | `test_fifo_multiple_partial_withdrawals_preserve_excess_and_progress` |
| 23 | Multiplos recolhimentos | mesmo teste FIFO e `test_assignment_replaces_owner_and_manual_results_keep_post_close_withdrawal` |
| 24 | Recolhimento multi-item | `test_multi_item_and_money_entry_and_withdrawal_keep_numeric_precision` |
| 25 | Dinheiro no recolhimento | teste multi-item/dinheiro acima |
| 26 | Valor acima do saldo | `test_fifo_multiple_partial_withdrawals_preserve_excess_and_progress` |
| 27 | FIFO | teste FIFO local e teste PostgreSQL real |
| 28 | Concorrencia de recolhimento | `test_postgres_farm_tickets_serializes_open_operations_fifo_and_admin_races` |
| 29 | Assumir | `test_assignment_replaces_owner_and_manual_results_keep_post_close_withdrawal` |
| 30 | Troca de responsavel | mesmo teste de atribuicao acima |
| 31 | Aprovacao manual abaixo de 100% | mesmo teste de atribuicao/aprovacao acima |
| 32 | Aprovacao automatica | `test_valid_edit_requires_new_proof_and_can_auto_approve` e testes de confirmacao em 100% |
| 33 | Aprovacao por edicao | `test_valid_edit_requires_new_proof_and_can_auto_approve` |
| 34 | Finalizacao incompleta | `test_incomplete_finalization_keeps_withdrawal_then_new_goal_freezes_balance` |
| 35 | Recolhimento apos aprovacao | teste de atribuicao/aprovacao acima |
| 36 | Recolhimento apos finalizacao | teste de finalizacao incompleta acima |
| 37 | Saldo zero | testes de recolhimento total e saida sem saldo |
| 38 | Excedente | `test_fifo_multiple_partial_withdrawals_preserve_excess_and_progress` |
| 39 | Saida do membro sem saldo | `test_manual_delete_rules_member_leave_without_balance_and_multi_guild_isolation` |
| 40 | Saida com saldo | `test_member_left_balance_policy_and_same_cycle_ticket_stays_non_operational` |
| 41 | Retorno no mesmo ciclo | teste de lifecycle/multi-guild, que exige conflito sem reativacao |
| 42 | Fim de ciclo incompleto | `test_cycle_event_waits_for_timely_claim_then_confirms_before_closing` |
| 43 | Fim de ciclo aprovado com saldo | `test_cycle_close_preserves_unwithdrawn_balance_without_synthetic_allocations` |
| 44 | Nova Meta substituindo membro | `test_incomplete_finalization_keeps_withdrawal_then_new_goal_freezes_balance` |
| 45 | Exclusao manual bloqueada com saldo | `test_manual_delete_rules_member_leave_without_balance_and_multi_guild_isolation` |
| 46 | Exclusao manual valida | mesmo teste, com resultado `CLOSED_MANUALLY` |
| 47 | Recuperacao de canal | `test_runtime_recovers_category_panel_log_ticket_channel_and_thread_idempotently` |
| 48 | Recuperacao de categoria | mesmo teste de runtime e teste do limite real de 50 canais |
| 49 | Recuperacao de painel | mesmo teste de runtime |
| 50 | Recuperacao de log | mesmo teste de runtime |
| 51 | Recuperacao de thread | mesmo teste de runtime |
| 52 | Reconstrucao de eventos | `test_thread_recovery_reconstructs_all_events_once_in_sequence` |
| 53 | Limpeza S3 | `test_storage_cleanup_retains_until_thread_copy_then_retries` e teste MinIO real |
| 54 | Isolamento multi-guild | teste de lifecycle/multi-guild e filtros por `guild_id` |
| 55 | Corrida aprovacao manual x automatica | teste PostgreSQL real, com uma unica sequencia/efeito final |
| 56 | Corrida edicao x recolhimento | teste PostgreSQL real, com `FOR UPDATE` e um unico vencedor |

## Regressões adicionais obrigatórias

Os seguintes testes cobrem explicitamente as quatro correcoes finais do plano:

- `test_administrative_actions_do_not_cancel_awaiting_proof`;
- `test_proof_received_before_deadline_survives_processing_after_deadline`;
- `test_cycle_event_waits_for_timely_claim_then_confirms_before_closing`;
- `test_cycle_event_rejects_claim_received_after_effective_end`;
- `test_tenth_infrastructure_failure_becomes_recorded_recoverable_failure`;
- `test_cycle_close_preserves_unwithdrawn_balance_without_synthetic_allocations`;
- `test_manual_channel_delete_preserves_consolidated_result`;
- `test_external_and_planned_deletions_keep_historical_result`.

## Suites reais condicionais

PostgreSQL:

```powershell
$env:YUNO_TEST_POSTGRES_URL = "postgresql+asyncpg://.../yuno_test"
python -m pytest -q backend/tests/test_platform_postgres.py
```

MinIO/S3 privado:

```powershell
$env:YUNO_TEST_MINIO_ENDPOINT = "http://127.0.0.1:9000"
$env:YUNO_TEST_MINIO_BUCKET = "yuno-farm-proofs"
$env:YUNO_TEST_MINIO_ACCESS_KEY = "..."
$env:YUNO_TEST_MINIO_SECRET_KEY = "..."
python -m pytest -q backend/tests/test_farm_tickets_minio.py
```

## Roteiro Discord do ambiente de teste

- T-01: abrir ticket proprio e para membro, confirmar que repeticao retorna o
  mesmo canal e que somente `/yuno configurar` permanece publico.
- T-02: publicar troca do cargo administrador e confirmar reconciliacao imediata
  das permissoes dos canais existentes.
- T-03: percorrer lancamento, edicao, prova, retry, recolhimento, aprovacao,
  finalizacao e exclusao com os bloqueios esperados.
- T-04: reiniciar API/bot durante timeout e durante retry de prova.
- T-05: apagar controladamente painel global, canal, categoria, log, painel do
  ticket e thread; confirmar recovery e reconstrução cronologica.
- T-06: encerrar ciclo/trocar Meta com saldo e comparar painel, log e snapshot SQL.
- T-07: confirmar upload privado no MinIO, copia na thread antes do cleanup e
  retencao quando a copia falha.

O relatorio final deve registrar SHA, Alembic head, contagens/checksums da
migracao, resultados PostgreSQL/MinIO, IDs dos recursos Discord de teste e
qualquer comportamento nao observado.
