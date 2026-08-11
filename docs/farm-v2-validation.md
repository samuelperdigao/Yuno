# Farm V2 — validação, cutover e rollback

## Pré-condições

- Executar backup do banco e confirmar restauração antes da migração.
- Validar a revisão Alembic atual e aplicar `f2a1b3c4d5e6` em homologação.
- Confirmar `CONTROL_PLANE_ENABLED=true`; a árvore pública deve conter somente
  `/yuno configurar`.
- Manter `farm_tickets` em operação até o aceite do novo fluxo.

## Roteiro manual no servidor de teste

1. Rodar `/yuno configurar` e abrir **Farm** na Central.
2. Definir categorias e canais em **Destinos**; publicar as permissões.
3. Criar mais de cinco produtos, criar e ativar um template com todos eles.
4. Criar e agendar um ciclo; ativar o runtime e publicar os painéis.
5. Como membro elegível, abrir o próprio ticket no painel público.
6. Enviar duas entregas parciais com links de comprovante.
7. Como revisor, pedir correção em uma entrega e aprovar a substituta.
8. Confirmar que somente entregas aprovadas alteram o progresso.
9. Como gestor, abrir um ticket para outro membro e confirmar que o canal é do
   beneficiário e a auditoria registra o gestor como executor.
10. Reiniciar bot e API; confirmar que painéis, jobs e views continuam ativos.
11. Apagar um painel de teste e usar **Publicar painéis** para recuperá-lo sem
    duplicar a identidade lógica.
12. Encerrar o ciclo duas vezes e confirmar idempotência, fechamento dos tickets
    e ausência de logs duplicados.

## Cutover por guild

1. Na Central do Farm, usar **Preparar cutover**.
2. Se houver ticket legado ativo, a execução fica `failed` e o corte é bloqueado.
3. Com inventário pronto, guardar o ID da execução em estado `ready`.
4. Usar **Cutover / rollback**, informar o ID e digitar `CONFIRMAR`.
5. Confirmar `runtime_mode=domain`, `lifecycle=active`, diagnósticos sem erro e
   painéis publicados antes de considerar o corte aceito.

O cutover não importa ticket ativo, não faz dual-write e não remove tabela ou
mensagem legada.

## Rollback operacional

Antes de qualquer escrita marcada como incompatível:

1. Abrir **Cutover / rollback**.
2. Informar a execução concluída, escolher `rollback` e digitar `CONFIRMAR`.
3. Confirmar `runtime_mode=legacy`.
4. Reconciliar os painéis legados e pausar os painéis Farm V2.
5. Preservar todas as tabelas `farm_*` novas para análise e novo cutover.

Se `checkpoint.incompatible_writes=true`, o sistema falha fechado: não executar
downgrade destrutivo; corrigir por roll-forward.

## Evidência local de 11/08/2026

- Contrato backend/Discord: compatível, sem divergências.
- Importação FastAPI: 23 operações em 20 caminhos internos do Farm.
- Componentes Discord: modais e views construídos sem violar limites do SDK.
- Alembic offline até `f2a1b3c4d5e6`: concluído.
- Testes focados: 40 passaram.
- Suíte completa: 114 passaram, 1 ignorado, 2 falharam e 12 tiveram erro.

Os 14 casos incompletos foram bloqueados pela política do Windows ao carregar
`_greenlet`; não houve falha funcional distinta nesses casos. Repetir a suíte
em Linux/container ou host que permita a DLL é gate para deploy/cutover.
