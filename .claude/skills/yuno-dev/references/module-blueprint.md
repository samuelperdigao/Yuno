# Blueprint de módulo do Yuno

Use este roteiro para qualquer módulo novo ou reconstruído. Não implementar enquanto as decisões que afetam domínio, dados ou UX ainda estiverem abertas.

## 1. Diagnóstico

- Definir objetivo, problema resolvido e resultado esperado.
- Identificar atores humanos, sistema e integrações.
- Mapear comportamento atual apenas como evidência.
- Produzir matriz **preservar / redesenhar / descartar / migrar**.
- Registrar decisões pendentes que realmente dependem do produto.

## 2. Domínio

Definir explicitamente:

1. Entidades e value objects.
2. Identidades e relacionamentos.
3. Estados permitidos.
4. Transições e seus atores.
5. Regras de negócio.
6. Invariantes controladas pelo Yuno.
7. Configurações permitidas ao cliente.
8. Configurações proibidas.
9. Eventos de domínio e efeitos colaterais.
10. Ciclo de vida, retenção e histórico.

Não iniciar pelo formato do modal ou por colunas existentes. Limites da interface não reduzem cardinalidade ou expressividade do domínio.

## 3. Casos de uso e permissões

Para cada ação, declarar:

- ator autorizado e pré-condições;
- entrada semântica, não payload de UI;
- estado lido e estado alterado;
- validações e invariantes;
- auditoria e logs;
- resultado visível;
- idempotência, concorrência e recuperação de falha.

Produzir matriz com atores × ações. Incluir administrador da Central, operador/revisor, membro e automação quando aplicável.

## 4. Configuração e publicação

Separar:

- rascunho administrativo;
- validação de domínio e Discord;
- prévia sem efeito público;
- versão publicada imutável;
- configuração efetiva consumida pelo Runtime;
- referências de painéis publicados.

Runtime nunca lê rascunho. Publicação deve ser atômica do ponto de vista do domínio ou possuir compensação testada.

Definir versionamento do schema, revisão otimista e comportamento de duas sessões concorrentes. A Central deve informar erro acionável, sem sobrescrever silenciosamente.

## 5. UX administrativa

Descrever jornada completa na Central:

- entrada e resumo de estado;
- configuração por etapas;
- seletores e modais necessários;
- validação progressiva;
- prévia;
- confirmação de publicação;
- diagnóstico e correção;
- recuperação/republicação de painel apagado.

Não converter comandos antigos diretamente em botões. Agrupar tarefas pela intenção do administrador.

## 6. UX operacional

Definir painéis usados por membros e operadores:

- ações disponíveis por estado;
- feedback efêmero e público;
- paginação e limites da API do Discord;
- comportamento após restart;
- mensagens removidas, canais movidos e permissões alteradas;
- acessibilidade de textos, labels e confirmações destrutivas.

Views chamam serviços; não decidem regra de negócio.

## 7. Persistência e serviços

Definir:

- tabelas, chaves, constraints, índices e cascatas;
- quais dados realmente justificam JSON;
- schemas de entrada e saída;
- serviços de aplicação e domínio;
- transações e locks;
- APIs internas bot→backend;
- consultas, paginação e filtros;
- auditoria e observabilidade.

Domínio com relacionamentos, agregações ou consultas próprias usa modelo relacional. `SystemRecord` não é atalho universal.

## 8. Automações

Para listeners e jobs, declarar:

- gatilho, timezone e política de atraso;
- exclusão mútua e reentrada;
- checkpoint/idempotência;
- retry e dead-letter ou compensação;
- comportamento durante indisponibilidade;
- auditoria e notificação de falha.

## 9. Migração e compatibilidade

Somente após fechar o modelo novo:

1. Inventariar dados legados.
2. Classificar preservar, transformar, arquivar ou descartar com autorização.
3. Definir mapeamento e validações de contagem/integridade.
4. Planejar backfill repetível e observável.
5. Definir convivência temporária e fonte de verdade.
6. Definir corte, rollback e remoção do adaptador.

Nunca fazer dual-write indefinido. Nunca usar o schema legado para empobrecer o domínio novo.

## 10. Testes e aceite

Cobrir no mínimo:

- invariantes e transições válidas/inválidas;
- isolamento entre guilds;
- permissões por ação;
- concorrência e idempotência;
- persistência e restart;
- migração e repetição do backfill;
- publicação criar, atualizar, mover, recuperar e compensar falha;
- painel persistente e limites do Discord;
- jobs atrasados, repetidos e interrompidos;
- rollback e preservação de dados.

Critérios de aceite devem ser observáveis por produto, não apenas “endpoint retorna 200”.

## Saída obrigatória do planejamento

Entregar um documento fechado contendo:

1. Diagnóstico de preservar e descartar.
2. Arquitetura alvo.
3. Domínio, entidades e relacionamentos.
4. Estados, transições e invariantes.
5. Matriz de permissões.
6. Fluxos administrativos e dos membros.
7. Painéis, modais e seletores.
8. Modelo de dados e contratos de serviço/API.
9. Auditoria, logs e automações.
10. Concorrência, idempotência e recuperação.
11. Migração, compatibilidade e rollback.
12. Testes e critérios de aceite.
13. Riscos e decisões pendentes.
14. Ordem exata de implementação.
15. Arquivos prováveis a alterar.
16. Prompt final de execução.

## Ordem de implementação após aprovação

1. Domínio e persistência.
2. Migração Alembic e backfill testável.
3. Serviços e APIs.
4. Cliente interno.
5. Central administrativa.
6. Publicador e painéis operacionais.
7. Jobs/listeners.
8. Compatibilidade e corte.
9. Testes completos.
10. Rollout monitorado e remoção do legado após aceite.
