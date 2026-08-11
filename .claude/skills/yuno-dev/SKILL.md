---
name: yuno-dev
description: Arquitetura, planejamento, desenvolvimento, testes e operação do Yuno, plataforma Discord SaaS multi-tenant para organizações de FiveM. Use sempre que a tarefa envolver o repositório Yuno, a Central de Gestão, Control Plane, módulos operacionais, Farm, FastAPI, SQLAlchemy, Alembic, Discord.py, painéis persistentes, migração de dados, licenças, auditoria, dashboard, deploy ou análise do Morro do Mineiro como legado. Para módulos novos ou reconstruídos, aplica desenho domain-first sem herdar comandos, schemas, interfaces ou fluxos antigos por conveniência.
---

# Yuno: desenvolvimento domain-first

Trate o Yuno como uma plataforma configurável de gestão e automação, administrada dentro do Discord. A Central de Gestão é o **Control Plane**; os módulos e automações são o **Runtime**.

Fluxo oficial:

```text
requisito do produto
→ domínio e regras
→ persistência e serviços
→ Central administrativa
→ painéis operacionais
→ automações
```

As instruções atuais do usuário e os documentos vigentes do projeto prevalecem sobre esta skill. O comportamento factual do repositório prevalece sobre mapas desatualizados.

## Começar com contexto mínimo

1. Ler `references/mapa-yuno.md` para localizar a implementação atual e seus acoplamentos transitórios.
2. Para módulo novo ou reconstruído, ler `references/architecture-upgrade.md` e `references/module-blueprint.md`.
3. Para Farm, ler também `references/farm-v2.md`.
4. Consultar `references/mapa-mdm.md` e `references/legacy-audit.md` somente quando o legado puder revelar requisitos, casos de borda ou dados a preservar.
5. Abrir apenas arquivos diretamente relacionados. Ignorar caches, builds, bancos locais, logs, anexos e ambientes virtuais.

Não prolongar descoberta quando as decisões já estiverem fechadas. Não implementar um redesenho enquanto domínio, estados, interfaces, persistência, migração e aceite ainda exigirem decisões do implementador.

## Escolher o fluxo correto

### Módulo novo ou reconstruído

Seguir integralmente o blueprint. Não começar por cog, botão, modal, tabela existente ou comando antigo. Produzir primeiro uma arquitetura funcional executável.

### Correção pontual

Diagnosticar e corrigir no menor escopo seguro. Não forçar uma reescrita domain-first em bug isolado de um fluxo já aprovado.

### Deploy ou operação

Preservar mudanças alheias, executar testes proporcionais, criar backup, validar migração, health, serviços e rollback. Nunca imprimir segredos. Não fazer push, deploy ou alteração de produção sem autorização explícita na tarefa atual.

## Regras permanentes de produto

- Com a Central habilitada, o único slash público é `/yuno configurar`.
- Status, diagnóstico, configuração, permissões e publicação pertencem à Central.
- Ações dos membros pertencem a painéis operacionais persistentes.
- Botão, modal, seletor, painel e comando são interfaces; lógica de negócio fica em serviços e domínio testável.
- O Yuno controla invariantes, estados, transições, segurança, integridade e campos semânticos.
- O cliente controla dados, identidade, canais, categorias, cargos, produtos, quantidades, prazos, textos permitidos e regras parametrizáveis.
- O Yuno se adapta ao servidor: selecionar estrutura existente deve ser possível; criar estrutura nova é opção, não obrigação.
- Nenhum ID Discord pode ser constante. Todo estado multi-tenant deve ser isolado por `guild_id`.
- Limites do Discord pertencem à camada de interface; não limitar coleções do domínio para caber em um modal ou select.

## Política sobre legado

O Yuno antigo e o Morro do Mineiro podem ser lidos para descobrir:

- requisitos e comportamentos úteis;
- casos de borda e falhas reais;
- integrações existentes;
- dados que não podem ser perdidos;
- regras já comprovadas em produção.

Eles não são fonte de verdade da nova arquitetura. É proibido:

- copiar automaticamente schema, comando, view ou fluxo;
- converter comando antigo em botão sem redesenhar o caso de uso;
- adaptar a Central para caber no legado;
- manter abstração ruim apenas por compatibilidade;
- usar `dashboard_fields`, `seed_from_legacy` ou `project_to_legacy` como contrato definitivo;
- tratar publicadores ou comandos `/setup_*` como arquitetura-alvo.

Reutilizar somente componentes que preservem o novo domínio e reduzam complexidade. Compatibilidade temporária precisa de escopo, prazo de remoção, telemetria e rollback.

## Fundações que podem permanecer

Avaliar individualmente e preservar quando adequados: Python, Discord.py, FastAPI, Pydantic, SQLAlchemy assíncrono, Alembic, PostgreSQL, Redis, bot→API, autenticação interna, auditoria, logging, registry modular, views persistentes, infraestrutura de publicação, Docker, backup e deploy.

Não criar um segundo bot ou backend. Não reescrever infraestrutura útil apenas para parecer nova.

## Princípios de implementação

- Modelar relações importantes com tabelas, chaves, constraints e índices. Usar JSON apenas quando houver flexibilidade real.
- Toda alteração em modelos relacionais exige migração Alembic revisada, upgrade testado e rollback documentado.
- Runtime nunca lê rascunho; somente configuração publicada e válida.
- Operações sensíveis geram auditoria com `guild_id`, ator, ação, entidade e dados mínimos úteis.
- Escritas concorrentes precisam de revisão otimista, lock ou chave de idempotência conforme o caso.
- Views persistentes usam `timeout=None`, `custom_id` estável e registro no boot.
- Resolver canais e cargos por ID. Renomear ou mover estrutura do cliente não é erro.
- Fazer `defer` antes de I/O demorado; nunca tentar abrir modal após responder à interação.
- Não vazar traceback, token ou payload sensível ao Discord ou aos logs.

## Ordem de reconstrução

Começar pelo Farm e validar o padrão completo. Migrar os demais módulos um por vez, sem big bang. A lógica operacional antiga permanece ativa até a substituição do módulo estar publicada, validada e reversível.

## Verificação mínima

- Testes existentes e novos verdes.
- Apenas `/yuno configurar` na árvore ativa da Central.
- Nenhum texto orienta slash legado.
- Nenhum ID Discord hardcoded, SQLite no bot ou estado global sem `guild_id`.
- Painéis sobrevivem a restart e publicação repetida é idempotente.
- Migração preserva dados declarados como obrigatórios e pode ser auditada.
- Fluxos administrativos e de membros funcionam em servidor Discord de teste.
- Rollback não exige apagar histórico ou executar downgrade destrutivo por padrão.

## Comunicação

Responder em português do Brasil. Entregar decisão e resultado antes da explicação. Apontar custo escondido e incompatibilidades reais sem criar objeções artificiais.

## Referências

- `references/architecture-upgrade.md`: visão e limites da arquitetura nova.
- `references/module-blueprint.md`: especificação obrigatória para cada módulo redesenhado.
- `references/farm-v2.md`: briefing do primeiro módulo.
- `references/mapa-yuno.md`: mapa factual do repositório atual.
- `references/mapa-mdm.md`: inventário do legado, sem prescrever arquitetura.
- `references/legacy-audit.md`: método para extrair evidências e planejar migração.
