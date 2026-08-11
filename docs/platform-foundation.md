# Fundação domain-first da Yuno Platform

Esta fundação é independente dos módulos antigos. O novo registry do backend
descobre apenas pacotes em `backend/app/domain_modules/`; o registry Discord
descobre apenas adapters em `bot/yuno_bot/domain_modules/`. O Farm V2 possui
contrato backend e adapter Discord com a mesma chave `farm`.
`bot/yuno_bot/commands/` continua sendo executado exclusivamente pelo
loader legado enquanto as funcionalidades existentes ainda precisarem ser
preservadas, mas não fornece contratos, schemas, painéis, capabilities ou jobs
à plataforma nova.

## Como o primeiro módulo entra

O desenho aprovado para o primeiro módulo está em
[`farm-v2-plan.md`](farm-v2-plan.md). Ele mantém entidades de negócio fora das
tabelas transversais e define convivência sem dual-write com o Farm legado.

Um módulo domain-first adiciona dois pacotes com a mesma chave:

```text
backend/app/domain_modules/<module_key>/
  __init__.py -> MODULE_DEFINITION: ModuleDefinition

bot/yuno_bot/domain_modules/<module_key>/
  __init__.py -> MODULE_UI: ModuleUIAdapter
```

Nenhuma edição no core ou branch `if module_key == ...` é necessária. O
backend publica seu contrato em `GET /internal/platform/manifest`; o bot faz o
handshake da chave e da versão antes de habilitar o adapter Discord.

O `ModuleDefinition` compõe somente os contratos usados pelo módulo:

- manifesto e dependências;
- configuração tipada;
- capabilities;
- lifecycle;
- painéis e ações;
- jobs;
- health checks;
- migração.

Um módulo sem configuração, painel, job ou migração não declara esses
componentes.

## Fronteiras persistidas

As tabelas `module_instances`, `module_config_*`,
`module_permission_grants`, `panel_instances`, `automation_*`,
`delivery_*`, `audit_entries`, `module_migration_runs` e
`interaction_receipts` armazenam somente mecanismos transversais. Entidades de
negócio continuam em tabelas do próprio domínio.

Rascunhos usam revisão otimista. Publicações são snapshots imutáveis e o
runtime consulta somente a versão efetiva. Rollback publica uma nova versão
monotônica. Painéis têm identidade lógica tenant-scoped. Jobs, entregas e
interações têm chaves de idempotência persistidas.

## Segurança

- Toda rota de recurso confirma `guild_id`.
- Mutações administrativas recebem `ActorContext` e o backend revalida dono,
  `administrator`, `manage_guild` ou cargo administrativo da Central.
- Ações operacionais usam capabilities e grants da configuração publicada.
- Recursos carregados por ID nunca são utilizados sem o filtro da guild.
- Auditoria redige chaves de segredo e registra correlação.

## Migração e rollback

A migração Alembic `c1d2e3f4a5b6` é aditiva. Ela não copia dados antigos, não
ativa módulo e não muda fonte de verdade. O corte funcional acontece somente
por `module_migration_runs`, por guild e módulo, depois do estado `ready`.

Antes de escrita incompatível, o runtime pode voltar ao modo de origem. Depois
de `checkpoint.incompatible_writes=true`, o endpoint de rollback falha fechado
e exige roll-forward. O downgrade Alembic não é o rollback operacional padrão.

## Estado da implementação

O backend descobre `backend/app/domain_modules/farm/`, publica seu contrato,
registra onze tabelas relacionais e expõe o vertical interno tenant-safe. A
migração `f2a1b3c4d5e6` é somente aditiva e não muda nenhuma guild de runtime.
O adapter `bot/yuno_bot/domain_modules/farm/` fornece Central administrativa,
painéis público/ticket/revisão, jobs e renderers da outbox. O coordinator passa
a executar esses handlers depois do handshake de contrato. O Farm legado segue
intacto e identificado na Central para convivência e rollback; nenhuma guild é
movida para `domain` sem inventário, validação e confirmação explícita.
