# Farm V2 — plano funcional e técnico fechado

Status: MVP implementado localmente; validação online e cutover pendentes
Data: 11 de agosto de 2026
Escopo: primeiro módulo domain-first do Yuno

Progresso da execução:

- [x] Contrato e registry backend.
- [x] Estados, invariantes e schemas de entrada.
- [x] Onze modelos relacionais próprios do domínio.
- [x] Migração Alembic aditiva encadeada à fundação.
- [x] Testes puros, metadata e DDL offline SQLite/PostgreSQL.
- [x] Serviços e APIs do domínio.
- [x] Adapter Discord, Central e painéis.
- [x] Jobs, outbox, inventário e fluxo reversível de cutover.
- [ ] Validação PostgreSQL/Discord no servidor de teste e aceite do produto.

## 1. Decisão de produto

O Farm V2 será um domínio novo. O Farm legado continuará ativo por guild até o
corte explícito daquela guild e será usado somente como fonte de evidências e
dados históricos.

O módulo administrará ciclos configuráveis de entrega:

```text
administrador configura e publica o módulo
→ gestor cria template e ciclo
→ membro abre ticket ou gestor abre para o membro
→ membro faz uma ou mais entregas
→ revisor decide cada entrega
→ progresso é recalculado
→ ciclo encerra de forma idempotente
```

O MVP não inclui pagamento, moeda, punição, advertência automática, semana fixa
ou produtos predefinidos. Essas capacidades só poderão nascer como decisões de
produto posteriores.

## 2. Diagnóstico do que existe

### Preservar como infraestrutura

- FastAPI, SQLAlchemy assíncrono, Alembic e autenticação bot → API.
- Fundação domain-first em `backend/app/platform/` e `bot/yuno_bot/platform/`.
- Registry isolado em `domain_modules/`.
- Versões publicadas, revisão otimista, grants, lifecycle e runtime mode.
- Identidade lógica e recuperação de painéis.
- Jobs com lease e idempotência, outbox, auditoria e recibos de interação.
- Helpers genéricos de publicação/rollback que respeitem o domínio novo.
- Resolução de canais e cargos por ID.

### Preservar como requisito, redesenhando a implementação

- Ticket individual e privado por membro.
- Gestor poder abrir um ticket para outro membro.
- Beneficiário ser o dono dos dados; executor ser registrado separadamente.
- Múltiplas entregas e comprovantes.
- Progresso por produto e progresso geral.
- Fila de revisão e responsável administrativo.
- Histórico completo antes de remover ou arquivar um canal.
- Repetição de logs e manutenção após falhas transitórias.
- Snapshot da identidade do membro e das metas no ciclo.

### Descartar como arquitetura

- Ciclo identificado por `week_id` e calendário semanal obrigatório.
- Metas e valores de entrega em JSON como fonte principal.
- Limite de cinco produtos derivado de modal.
- Nomes de produtos como chave relacional.
- Estados livres em strings sem máquina de transição central.
- API com dezenas de operações sem ator e tenant no contrato comum.
- Publicadores `/setup_farm_*` e `/farm ranking`.
- Cálculo que contabiliza qualquer entrada não marcada como `revisao`.
- Exclusão física do canal como representação da exclusão do domínio.
- Cargos, categorias, pastas e nomes específicos como regra do Farm.

### Manter apenas para consulta ou migração

- `farm_ticket_configs`.
- `farm_weekly_goals`.
- `farm_tickets`.
- `farm_ticket_entries`.
- `farm_ticket_actions`.
- Referências antigas de painel em `GuildConfig.settings`.

## 3. Limites do MVP

### Incluído

- Catálogo dinâmico de produtos e unidades.
- Templates reutilizáveis e versionados.
- Ciclos com datas, metas congeladas e participação configurável.
- Tickets individuais.
- Abertura própria e abertura administrativa para membro.
- Entregas parciais com um ou mais comprovantes.
- Revisão, aprovação, rejeição e solicitação de correção.
- Progresso por produto e geral.
- Painel público, painel do ticket e fila de revisão.
- Ativação e encerramento automatizados.
- Auditoria, idempotência, recuperação e isolamento multi-tenant.
- Convivência e corte por guild.

### Fora do primeiro corte

- Pagamento e divisão financeira.
- Ranking competitivo como requisito central.
- Quota com advertência ou punição automática.
- Integração automática com Ausência, Hierarquia ou Advertência.
- Dashboard web.
- Importação automática de configuração antiga.
- Migração de tickets ativos entre os dois runtimes.

## 4. Vocabulário e entidades

### `FarmProduct`

Produto configurável da guild. Possui nome, descrição opcional, unidade,
precisão decimal de 0 a 3 e estado ativo/arquivado. Arquivar impede novo uso,
mas não altera templates ou ciclos existentes.

### `FarmTemplate`

Versão imutável de uma definição reutilizável. Versões do mesmo template
compartilham uma chave lógica. Depois que uma versão for usada por um ciclo,
qualquer edição cria a próxima versão.

### `FarmTemplateItem`

Associa produto e quantidade padrão à versão do template.

### `FarmCycle`

Ocorrência temporal criada a partir de uma versão de template. Contém título,
timezone, início, fim, prazo de revisão, modo de participação e política de
comprovante. A ativação congela suas metas.

### `FarmCycleGoal`

Snapshot relacional de produto, nome, unidade, precisão e quantidade exigida no
ciclo. Mudanças posteriores no catálogo ou template não o alteram.

### `FarmCycleParticipant`

Participante explicitamente atribuído quando o ciclo usar modo `assigned`.
Guarda o membro, quem atribuiu e quando. No modo `opt_in`, essa tabela não é
pré-requisito para abrir o próprio ticket.

### `FarmTicket`

Espaço individual do beneficiário dentro de um ciclo. O beneficiário é sempre
`member_id`; `created_by` identifica quem abriu. Existe no máximo um ticket por
guild, ciclo e membro, independentemente de seu estado.

### `FarmSubmission`

Entrega parcial imutável. Pode corrigir outra submissão por referência, mas a
original nunca é sobrescrita.

### `FarmSubmissionItem`

Quantidade entregue para uma meta do ciclo. Usa decimal compatível com a
precisão congelada da meta.

### `FarmProof`

Metadados de um comprovante: canal, mensagem, anexo/URL, tipo, autor e data. O
banco não armazena os bytes do arquivo.

### `FarmReview`

Decisão append-only sobre uma submissão, com revisor, decisão, justificativa e
data. A situação efetiva da submissão deriva da última decisão válida.

## 5. Estados e transições

### Produto

```text
active → archived
```

Produto arquivado não volta a ser selecionável. Se for necessário reutilizar o
nome, cria-se um novo produto com identidade própria.

### Template

```text
draft → active → archived
```

- `draft`: editável e não selecionável por ciclos publicados.
- `active`: imutável; edição cria nova versão em `draft`.
- `archived`: não cria ciclos novos.

### Ciclo

```text
draft → scheduled → active → closing → closed
  └──────────────→ cancelled
scheduled → draft
```

- `draft`: metas e datas editáveis.
- `scheduled`: validado e aguardando início.
- `active`: aceita tickets e entregas.
- `closing`: bloqueia novas entregas e resolve a fila anterior ao prazo.
- `closed`: terminal e somente leitura.
- `cancelled`: terminal; exige motivo e não apaga histórico.

O job de início move `scheduled` para `active` uma única vez. O job de fim move
`active` para `closing`. Se não houver submissões pendentes, fecha imediatamente;
caso existam, registra alerta e fecha automaticamente assim que a última for
decidida. Nenhuma entrega pendente é rejeitada silenciosamente pelo sistema.

### Ticket

```text
open → completed → closed
  └──────────────→ cancelled
completed → open  (somente por invalidação rastreável de revisão)
```

- `open`: aceita entregas enquanto o ciclo está ativo.
- `completed`: todas as metas foram atingidas com entregas aprovadas.
- `closed`: ciclo encerrado.
- `cancelled`: cancelamento administrativo com motivo.

### Submissão

```text
submitted → under_review → approved
                         → correction_requested
                         → rejected
submitted ───────────────→ approved | correction_requested | rejected
```

`under_review` é um claim temporário e não altera o progresso. Apenas
`approved` contabiliza. Uma correção cria nova submissão apontando para a
anterior; não edita valores ou comprovantes já auditados.

## 6. Invariantes

1. Toda entidade pertence a exatamente uma `guild_id`.
2. Nenhuma consulta por ID opera sem confirmar a guild.
3. Um ciclo usa uma versão de template e snapshots de metas imutáveis.
4. Um membro possui no máximo um ticket por ciclo.
5. `member_id` recebe crédito; `created_by`, `submitted_by` e `reviewed_by`
   identificam executores distintos.
6. Quantidades são maiores que zero e respeitam a precisão da meta.
7. Uma submissão contém ao menos um item e, no MVP, ao menos um comprovante.
8. Um item de submissão só referencia meta do mesmo ciclo e ticket.
9. Apenas entregas aprovadas compõem progresso.
10. Progresso exibido é limitado a 100%, mas o total real aprovado é mantido.
11. Ticket concluído não recebe nova entrega sem reabertura de domínio.
12. Ciclo em `closing`, `closed` ou `cancelled` não recebe nova entrega.
13. Revisões são append-only e executadas em transação com a transição.
14. Fechamento e publicação são idempotentes.
15. Runtime usa somente configuração publicada.
16. Canal ou mensagem apagada não apaga entidade de negócio.

## 7. Participação

Cada ciclo escolhe um dos modos:

- `opt_in`: membro elegível abre o próprio ticket.
- `assigned`: somente membros atribuídos podem possuir ticket; gestor pode
  atribuir e abrir em nome deles.

Elegibilidade deriva de capabilities/grants publicados, nunca de nome de cargo.
Bots não podem ser participantes. Abrir para outro membro exige capability
específica e registra beneficiário e executor separadamente.

## 8. Permissões

| Capability | Administrador Central | Gestor Farm | Revisor | Membro elegível | Automação |
|---|---:|---:|---:|---:|---:|
| `farm.configure` | sim | opcional | não | não | não |
| `farm.manage_catalog` | sim | sim | não | não | não |
| `farm.manage_cycles` | sim | sim | não | não | não |
| `farm.open_own_ticket` | sim | sim | sim | sim | não |
| `farm.open_ticket_for_member` | sim | sim | não | não | não |
| `farm.submit_own` | sim | sim | não | dono | não |
| `farm.review` | sim | opcional | sim | não | não |
| `farm.view_all` | sim | sim | sim | não | não |
| `farm.close_cycle` | sim | sim | não | não | sim |
| `farm.recover_panels` | sim | sim | não | não | sim |

O administrador da Central recebe bypass apenas em capabilities administrativas.
Acúmulo de papéis é permitido. Toda ação revalida os grants publicados no
backend no momento da execução.

## 9. Configuração publicada

A configuração transversal do módulo conterá somente opções de Runtime e
Discord, por exemplo:

```json
{
  "timezone": "America/Sao_Paulo",
  "ticket_category_ids": [],
  "public_panel_channel_id": null,
  "review_panel_channel_id": null,
  "log_channel_id": null,
  "proof_required": true,
  "panel": {
    "title": "Central de Farm",
    "description": "Acompanhe seus ciclos e entregas.",
    "color": "#FFC72C"
  }
}
```

Produtos, templates, ciclos, metas, tickets e entregas não ficam nesse JSON.
São entidades relacionais administradas por casos de uso próprios.

## 10. Jornada na Central

```text
/yuno configurar
→ Farm
→ Visão geral
→ Produtos
→ Templates
→ Ciclos
→ Permissões
→ Destinos Discord
→ Prévia
→ Publicar
```

### Visão geral

Exibe lifecycle, runtime mode, versão publicada, mudanças pendentes, ciclo
ativo, fila de revisão, saúde dos painéis e estado da migração.

### Produtos

Lista paginada com criar, editar enquanto não referenciado e arquivar. Modal
coleta nome, unidade e precisão. Limites do Discord afetam apenas a paginação.

### Templates

Lista versões, cria rascunho, adiciona produtos por select paginado, define
quantidades, valida e ativa. Editar versão ativa cria nova versão.

### Ciclos

Cria a partir de template, permite ajustar metas antes de agendar, define datas,
modo de participação e prazo de revisão. Exibe prévia do ciclo e pede
confirmação para agendar, ativar, cancelar ou fechar manualmente.

### Permissões

Mapeia cargos existentes às capabilities. Não cria cargos automaticamente sem
pedido. Mostra conflito, cargo removido e capability sem responsável.

### Destinos e publicação

Seleciona canais/categorias existentes ou oferece criação assistida. Prévia não
publica. Publicar cria nova versão imutável, reconcilia os painéis e só então
ativa o Runtime domain-first.

## 11. Painéis operacionais

### Painel público

- Ver ciclo atual e regras.
- Abrir meu ticket.
- Ver meu ticket/progresso.
- Gestor: abrir para membro.
- Consultar progresso geral somente quando configuração permitir.

### Painel do ticket

- Registrar entrega.
- Consultar comprovantes e histórico.
- Consultar progresso por produto.
- Ver solicitações de correção.

O registro de entrega usa seleção/paginação para escolher produtos, modais em
etapas para quantidades e, depois, coleta de anexo no canal. O domínio não fica
limitado a cinco produtos.

### Painel de revisão

- Fila paginada por ciclo, status e responsável.
- Claim opcional de uma submissão.
- Detalhe de itens e comprovantes.
- Aprovar, rejeitar ou pedir correção com justificativa.

### Persistência

Painéis usam `timeout=None`, `custom_id` estável e versionado e registro no boot.
O `custom_id` carrega somente ação e identidade opaca curta; o backend resolve
recurso e tenant. Mensagem removida fica `missing` e pode ser recuperada pela
Central sem duplicar a identidade lógica.

## 12. Modelo relacional

Tabelas novas propostas:

- `farm_products`
- `farm_templates`
- `farm_template_items`
- `farm_cycles`
- `farm_cycle_goals`
- `farm_cycle_participants`
- `farm_cycle_tickets`
- `farm_submissions`
- `farm_submission_items`
- `farm_proofs`
- `farm_reviews`

Constraints mínimas:

- produto: unicidade de nome normalizado por guild;
- template: unicidade de `guild_id + template_key + version`;
- item de template: unicidade de template + produto;
- meta: unicidade de ciclo + produto;
- participante: unicidade de ciclo + membro;
- ticket: unicidade de ciclo + membro;
- item de submissão: unicidade de submissão + meta;
- revisão: chave de idempotência única por guild;
- todas as FKs de entidades de negócio com tenant validado pelo serviço;
- índices por `guild_id`, ciclo, membro, status, prazo e fila de revisão.

Quantidades usarão `Numeric(18, 3)`. O serviço valida a precisão específica do
produto. JSON fica restrito a snapshots de apresentação, metadados realmente
flexíveis e payloads transversais de auditoria/outbox.

## 13. Serviços e API interna

Pacote de domínio:

```text
backend/app/domain_modules/farm/
  __init__.py
  definition.py
  models.py
  schemas.py
  services/
    catalog.py
    templates.py
    cycles.py
    tickets.py
    submissions.py
    reviews.py
    progress.py
    migration.py
```

Rotas sob o namespace existente:

```text
/internal/platform/guilds/{guild_id}/modules/farm/products
/internal/platform/guilds/{guild_id}/modules/farm/templates
/internal/platform/guilds/{guild_id}/modules/farm/cycles
/internal/platform/guilds/{guild_id}/modules/farm/tickets
/internal/platform/guilds/{guild_id}/modules/farm/submissions
/internal/platform/guilds/{guild_id}/modules/farm/reviews
```

Toda mutação recebe `ActorContext`, `expected_revision` quando editar agregado e
`idempotency_key` quando puder ser repetida por interação/retry. O backend
autoriza a capability, confirma tenant e produz auditoria na mesma transação.

Consultas são paginadas por cursor. O cliente do bot expõe serviços por domínio,
sem adicionar dezenas de métodos soltos ao `YunoAPI` legado.

## 14. Concorrência e idempotência

- Constraint de ciclo + membro impede tickets duplicados.
- Recibo de interação impede clique repetido criar duas entregas.
- Submissão usa idempotency key por interação.
- Claim de revisão usa revisão otimista e expiração.
- Decisão usa lock da submissão e rejeita revisão já superada.
- Progresso é calculado por soma relacional de itens aprovados; cache, se criado,
  é derivado e reconstruível.
- Ativação e fechamento usam jobs com chave `cycle:{id}:start|close`.
- Publicação de painel usa identidade lógica em `panel_instances`.
- Discord é atualizado via outbox; falha não desfaz o fato de domínio já
  confirmado, mas mantém entrega pendente e diagnóstico acionável.

## 15. Automações e falhas

### Jobs

- `farm.cycle.start`
- `farm.cycle.begin_closing`
- `farm.cycle.finish_closing`
- `farm.panel.reconcile`

Todos usam timezone convertido para UTC, lease, retry limitado, correlação e
resultado persistido. Job atrasado executa a transição ainda válida; se o estado
já avançou, termina com sucesso idempotente.

### Outbox

Notificações, atualização de painéis e logs Discord passam pela outbox. Depois
do limite de tentativas, permanecem `failed`, aparecem no diagnóstico e podem
ser reprocessados. Nenhum traceback é enviado ao Discord.

## 16. Migração e convivência

1. Criar somente tabelas novas, de forma aditiva.
2. Registrar Farm V2 no registry sem alterar guilds existentes.
3. Manter `runtime_mode=legacy` por padrão.
4. Fazer inventário por guild das cinco tabelas antigas e referências Discord.
5. Não importar configuração automaticamente: a Central começa como não
   configurada e exige configuração consciente.
6. Preservar ciclos/tickets antigos para consulta; não migrar ticket ativo para
   o meio de um ciclo novo.
7. Opcionalmente importar catálogo/template como rascunho explícito, exibindo
   cada transformação para confirmação.
8. Validar contagens, órfãos, anexos, guilds e checksums.
9. Rodar `shadow` apenas para leitura/diagnóstico, sem dual-write.
10. Cortar uma guild para `domain` somente sem ticket legado ativo ou após
    encerramento acordado.
11. Manter tabelas antigas intactas durante o período de observação.
12. Remover adapter e código legado somente em tarefa posterior, após aceite.

Rollback antes de escrita incompatível: retornar `runtime_mode` a `legacy`,
reconciliar os painéis antigos e manter todas as tabelas novas. Depois de escrita
incompatível, usar roll-forward; downgrade destrutivo não é rollback operacional.

## 17. Testes e critérios de aceite

### Domínio

- Estados e transições válidos e inválidos.
- Snapshot imutável de template e metas.
- Precisão e quantidade.
- Progresso somente com submissões aprovadas.
- Correção sem editar histórico.
- Dono/beneficiário separado de executor.

### Persistência/API

- Isolamento entre guilds em toda rota por ID.
- Unique constraints sob concorrência real.
- Revisão otimista e idempotência.
- Paginação e filtros.
- Auditoria com ator, recurso, correlação e redaction.
- Migração Alembic em banco vazio e cópia representativa.
- Claim concorrente em PostgreSQL.

### Discord

- Somente `/yuno configurar` na árvore pública.
- Configuração completa pela Central.
- Membro completa fluxo sem slash.
- Gestor abre para membro sem assumir a propriedade.
- Produtos acima de cinco funcionam por paginação.
- Views sobrevivem a restart.
- Canal movido/renomeado continua válido por ID.
- Painel apagado é recuperado sem duplicar.
- Falha Discord fica na outbox e pode ser repetida.

### Jobs

- Início e fechamento adiantados, atrasados e repetidos.
- Dois workers não executam a mesma transição.
- Ciclo com revisão pendente permanece em `closing`.
- Última revisão dispara fechamento exatamente uma vez.

### Aceite observável

1. Administrador configura e publica Farm pela Central.
2. Gestor cria template com mais de cinco produtos e agenda ciclo.
3. Membro abre ticket e envia duas entregas parciais com comprovantes.
4. Revisor pede correção em uma e aprova a substituta.
5. Progresso reflete somente decisões aprovadas.
6. Gestor abre ticket para outro membro e a auditoria separa ambos.
7. Restart não quebra painéis, estado ou jobs.
8. Encerramento repetido não duplica revisão, log ou fechamento.
9. Outra guild não lê nem altera qualquer recurso.
10. Rollback para legado preserva todo o histórico novo.

## 18. Baseline local

Execução em 11 de agosto de 2026 com dependências versionadas, em venv fora do
repositório:

Baseline antes da implementação:

```text
105 passed, 1 skipped, 2 failed, 12 errors
```

Suíte completa depois do MVP local:

```text
114 passed, 1 skipped, 2 failed, 12 errors
```

Os mesmos 14 casos não concluídos têm a mesma causa ambiental: a política de Controle
de Aplicativo do Windows bloqueou a DLL `_greenlet` instalada no venv temporário.
Os dois testes reportados como `failed` também chegam ao mesmo erro de greenlet.
Antes de implementar, o baseline deve ser repetido em ambiente onde a DLL seja
permitida ou no container oficial.

Não existe `AGENTS.md` neste checkout e `C:\Projetos\Yuno-main` não contém a
pasta `.git`; branch, commit e diff não podem ser confirmados localmente.

## 19. Ordem exata de implementação

1. Criar definição do módulo e testes de contrato no registry.
2. Criar enums, modelos relacionais e invariantes do domínio.
3. Criar migração Alembic aditiva e testes de upgrade.
4. Implementar catálogo e templates.
5. Implementar ciclos, snapshots e participantes.
6. Implementar tickets e abertura própria/administrativa.
7. Implementar submissões, comprovantes, revisões e progresso.
8. Expor APIs tenant-safe e cliente domain-first do bot.
9. Integrar configuração, grants e lifecycle da fundação.
10. Construir Central administrativa do Farm.
11. Construir painéis público, ticket e revisão.
12. Implementar jobs, outbox e reconciliador.
13. Implementar inventário/migração/cutover sem dual-write.
14. Executar testes específicos, suíte completa e PostgreSQL.
15. Validar manualmente no servidor Discord de teste.
16. Somente após aceite, planejar remoção do Farm legado.

## 20. Arquivos prováveis

### Criar

- `backend/app/domain_modules/farm/`
- `backend/app/api/platform/farm.py`
- migração Alembic do domínio Farm
- `bot/yuno_bot/domain_modules/farm/`
- testes de domínio, API, migração, jobs e UI do Farm

### Modificar de forma limitada

- `backend/app/api/platform/__init__.py` para montar o router do domínio.
- `backend/app/models.py` apenas se o mecanismo atual exigir registrar metadata.
- `bot/yuno_bot/api_client.py` ou adapter platform equivalente.
- documentação do módulo e operação.

Não modificar `bot/yuno_bot/commands/farm_tickets/` na primeira fatia. Ele é o
runtime legado e permanece disponível para rollback até o corte aprovado.

## 21. Riscos

- A fundação transversal ainda não foi validada contra PostgreSQL e Discord
  reais; isso é gate anterior ao corte.
- O checkout sem `.git` impede distinguir mudanças preexistentes por histórico.
- Coleta de anexo no Discord exige fluxo em etapas e recuperação após timeout.
- Grandes filas de revisão precisam paginação desde o primeiro corte.
- URL de anexo Discord não deve ser tratada como armazenamento permanente sem
  política posterior de retenção.
- Migração de dados antigos pode encontrar nomes de produto inconsistentes e
  entradas sem comprovante; devem virar warnings, nunca transformação silenciosa.

## 22. Decisões fechadas e futuras

Fechadas neste plano:

- Farm é o primeiro módulo domain-first.
- Fundação transversal existente será reutilizada.
- Domínio novo não lê nem projeta para schemas legados.
- Um ticket por membro/ciclo.
- Entregas e revisões imutáveis.
- Participação `opt_in` ou `assigned`.
- Comprovante obrigatório no MVP.
- Nenhuma punição, pagamento ou advertência automática.
- Nenhum limite de cinco produtos.
- Nenhum dual-write.

Decisões futuras que não bloqueiam o MVP:

- Armazenamento externo permanente dos comprovantes.
- Ranking e relatórios avançados.
- Integração com ausência/advertência.
- Políticas de retenção e anonimização.
- Planos comerciais por capacidade.

## 23. Prompt de execução

> Implemente o Farm V2 conforme `docs/farm-v2-plan.md`, usando a fundação
> domain-first existente e preservando integralmente o runtime legado até o
> cutover por guild. Comece por domínio, persistência e migração aditiva. Não
> converta comandos antigos em botões, não use os schemas legados como contrato,
> não faça dual-write e não limite produtos pela interface do Discord. Execute
> testes proporcionais após cada fatia e a suíte completa ao final. Não faça
> deploy, push, commit, migração de produção ou cutover sem autorização explícita
> na tarefa atual.
