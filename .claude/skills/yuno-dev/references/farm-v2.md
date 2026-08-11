# Farm v2: briefing do primeiro módulo

O Farm será o primeiro módulo redesenhado pelo blueprint. Esta referência fixa requisitos mínimos; o planejamento específico deve fechar detalhes e registrar decisões pendentes antes de implementar.

## Objetivo

Administrar ciclos configuráveis de entrega de produtos, com ticket individual por membro, múltiplas entregas parciais, comprovantes, revisão, progresso, histórico e encerramento automatizado.

Fluxo administrativo desejado:

```text
Central → Farm → configuração → templates → produtos
→ ciclos → permissões → painéis → publicação
```

Fluxo operacional desejado:

```text
ciclo ativo → painel público → membro abre ticket
→ entregas e comprovantes → revisão → aprovação/correção
→ progresso → fechamento
```

## Capacidades obrigatórias

- Tipos de Farm e produtos configuráveis.
- Coleções dinâmicas, sem limite de cinco produtos no domínio.
- `FarmTemplate` separado de `FarmCycle`.
- Templates reutilizáveis e versionamento/imutabilidade após uso definidos no planejamento.
- Ciclos com início, fim e metas próprias.
- Metas por produto e cálculo de progresso por produto e geral.
- Múltiplas entregas parciais e histórico completo.
- Comprovantes e metadados mínimos de autoria/data.
- Ticket individual por membro dentro do ciclo.
- Responsável administrativo e fluxo de revisão.
- Aprovação, rejeição ou solicitação de correção conforme regra aprovada.
- Logs, auditoria e recuperação após restart.
- Encerramento automático idempotente.
- Isolamento total por guild.
- Painéis persistentes e recuperação de painel apagado.

## Modelo conceitual mínimo

Avaliar entidades equivalentes a:

- `FarmTemplate`: definição reutilizável do tipo de Farm.
- `FarmTemplateItem`: produto e configuração padrão do template.
- `FarmCycle`: ocorrência temporal configurada a partir de um template.
- `FarmCycleGoal`: meta congelada de um produto no ciclo.
- `FarmTicket`: espaço individual do membro em um ciclo.
- `FarmSubmission`: uma entrega parcial submetida.
- `FarmSubmissionItem`: quantidades entregues por produto.
- `FarmReview`: decisão administrativa e justificativa.
- `FarmAction`: trilha operacional quando não coberta pela auditoria transversal.

Os nomes finais devem seguir a convenção do projeto. Não consolidar essas relações em um único JSON.

## Estados iniciais a validar

O planejamento deve confirmar, fundir ou rejeitar estes candidatos:

- Template: `active`, `archived`.
- Ciclo: `draft`, `scheduled`, `active`, `closing`, `closed`, `cancelled`.
- Ticket: `open`, `completed`, `closed`, `cancelled`.
- Entrega: `submitted`, `under_review`, `approved`, `correction_requested`, `rejected`.

Cada transição precisa declarar ator, pré-condição, efeitos, auditoria e reversibilidade. Não implementar os nomes acima sem validar o fluxo de produto.

## Invariantes mínimas

- Template e ciclo pertencem a uma única guild.
- Produtos e metas usados por um ciclo não mudam retroativamente por edição do template.
- Quantidades são positivas e usam unidade/precisão definida.
- Membro não abre tickets duplicados para o mesmo ciclo, salvo requisito explícito contrário.
- Entrega aprovada não é editada silenciosamente; correção gera novo evento ou revisão rastreável.
- Progresso contabiliza apenas estados definidos pelo domínio.
- Fechamento não pode executar duas vezes nem perder submissão concorrente.
- Runtime usa somente configuração publicada.

## Permissões a planejar

No mínimo:

- Administrador da Central: configura, publica e recupera estrutura.
- Gestor de Farm: cria/agenda/fecha ciclo e administra templates conforme delegação.
- Revisor: revisa, aprova, rejeita ou pede correção.
- Membro: abre seu ticket, envia entrega e consulta seu progresso.
- Automação: inicia/encerra ciclos e reconcilia painéis com identidade de sistema auditável.

Definir separação de funções e se o mesmo cargo pode acumular papéis.

## Central administrativa

Planejar páginas ou etapas para:

1. Estado e diagnóstico do módulo.
2. Tipos/templates.
3. Produtos e unidades.
4. Ciclos e metas.
5. Permissões.
6. Destinos Discord existentes ou criação assistida.
7. Aparência e textos permitidos.
8. Prévia.
9. Publicação e recuperação.

Paginação ou divisão em modais resolve limites do Discord sem limitar produtos no domínio.

## Painéis operacionais

Definir pelo menos:

- Painel público do ciclo: abrir ticket, consultar regras e progresso geral permitido.
- Painel do ticket: registrar entrega, anexar comprovante, consultar histórico e progresso.
- Painel de revisão: fila, detalhe, decisão e justificativa.
- Visões administrativas de ciclo: acompanhamento, fechamento e recuperação.

Avaliar quais painéis devem ser mensagens persistentes, mensagens do ticket ou respostas efêmeras.

## Persistência e concorrência

- Usar tabelas relacionais, foreign keys, unique constraints e índices por guild/ciclo/membro/status.
- Definir chave de idempotência para submissões, revisões e job de fechamento.
- Proteger criação simultânea de ticket com constraint de unicidade.
- Evitar cálculo de progresso baseado em JSON não indexável.
- Definir estratégia para anexos: armazenar IDs/URLs e metadados, não bytes no banco principal.
- Registrar revisão e transição em transação única.

## Legado e migração

Ler os fluxos antigos apenas para descobrir dados, casos de borda e comportamento observado. Não usar como contratos obrigatórios:

- `/setup_farm_tickets`;
- `/setup_farm_meta`;
- `/setup_farm_painel`;
- limite de produtos derivado de modal;
- semana fixa ou nomes de canais/cargos;
- formato atual de `FarmTicketConfig` ou `FarmWeeklyGoal`.

Depois de fechar o novo modelo, inventariar ciclos, tickets, entradas, ações, referências de painéis e configurações existentes. Definir quais registros serão migrados, arquivados ou mantidos somente para consulta.

## Fora da decisão automática

Não introduzir sem aprovação explícita:

- punição ou advertência automática por meta não cumprida;
- pagamento, moeda ou divisão financeira;
- fechamento semanal fixo;
- produtos padrão específicos de uma facção;
- acesso por nome de cargo.

## Aceite do padrão Farm

O Farm valida a arquitetura somente quando um administrador consegue configurar e publicar pela Central, um membro completa o fluxo sem slash, o estado sobrevive a restart, concorrência não duplica dados, o ciclo fecha de forma idempotente, a auditoria explica cada transição e o rollback preserva o histórico.
