# Tickets de Farm V2 — configuração publicada (resolvido)

> Investigado em 2026-08-26 e corrigido no mesmo dia. Esta versão substitui o
> briefing anterior, que continha três afirmações erradas — registradas abaixo
> para quem tiver lido a versão antiga.

## TL;DR

O módulo `farm_tickets` estava implementado no backend e no bot, mas nunca
provisionava nada porque exige configuração publicada
(`LifecyclePolicy(requires_published_configuration=True)`) e **não tinha página
administrativa na Central de Gestão**. Ele era o único módulo "platform v2"
sem `admin_pages`/`admin_actions` no `ModuleUIAdapter`.

Sintoma exato: ao selecionar "Tickets de Farm" no select da Central, o
`_dispatch_page` (`bot/yuno_bot/dashboard.py:357-363`) não encontrava a página
`overview` e respondia **"Este modulo ainda nao possui configuracao na
Central."**. O 404 `"Modulo sem configuracao publicada."` do backend era o
sintoma secundário, engolido no `on_ready` (`bot/yuno_bot/main.py:148-152`).

## Correções do briefing anterior

1. *"Nenhuma chamada a `configuration_draft`/`publish_configuration` no bot"* —
   errado. `registration/ui.py` e `tags/ui.py` já usavam o ciclo completo.
2. *"Não existe superfície de configuração para módulos platform v2"* — errado.
   A Central de Gestão (`/yuno configurar` → select de módulos) é genérica e já
   listava `farm_tickets` automaticamente via `ui_registry.all()`.
3. Logo, a recomendação de criar `/tickets configurar` + `cog.py` novo teria
   duplicado a superfície existente. Não foi seguida.

## O que foi implementado

- **`bot/yuno_bot/domain_modules/farm_tickets/admin.py`** (novo): página
  `overview` + fluxo de configuração na Central, no padrão de
  `registration`/`tags` — rascunho → selects → revisão → publicação.
  - Um `ChannelSelect` de categoria (`channel_types=[4]`), dois de canal de
    texto (painel e logs) e um `RoleSelect` (até 25 cargos administradores),
    cobrindo exatamente os 4 campos de `TICKETS_CONFIGURATION`.
  - `preflight()` bloqueia publicação com campo ausente, categoria/canal
    inexistente, painel e log no mesmo canal, cargo removido, `@everyone` como
    administrador, bot sem envio no canal ou sem Gerenciar Canais.
  - `build_grants()` monta o grant `everyone` de `farm_tickets.open_own` e um
    grant por cargo para as 9 `ADMIN_CAPABILITIES` — exatamente o que
    `_validate_permission_grants` (`definition.py:82`) exige no publish.
  - Após publicar, ativa o lifecycle. O provisionamento de categoria, canais e
    painel vem sozinho: `materialize_version` agenda `farm_tickets.reconcile`.
- **`__init__.py`**: registra `AdminPageDefinition("overview", render_admin)` e
  as 8 `AdminActionDefinition`.
- **`runtime.py`**: o branch `farm_tickets.reconcile` agora checa
  `published_config_version_id` e retorna `{"skipped": "unpublished_configuration"}`
  em vez de depender do 404 ser engolido lá em cima — "módulo ligado, ainda não
  configurado" virou estado explícito.

### Rascunho parcial: limitação do contrato

`administrator_role_ids` é obrigatório com `min_length: 1`, então o backend
recusa (422) qualquer rascunho sem cargo administrador — não dá para gravar
configuração pela metade. Enquanto o primeiro cargo não é escolhido, as demais
seleções ficam em memória de sessão (`admin._pending`) e são gravadas juntas
assim que o rascunho fica válido. A página avisa isso ao administrador. Se a
sessão cair antes disso, as seleções se perdem — trocar isso exigiria relaxar o
contrato e mover a exigência de "pelo menos um cargo" para o publish.

## Verificação executada

- `backend/tests/test_farm_tickets_discord.py`: 8 testes novos (17 no arquivo),
  incluindo um que alimenta o validador real do backend
  (`_validate_permission_grants`) com os grants montados pelo bot — é o que
  trava drift entre `admin.ADMIN_CAPABILITIES` e `definition.ADMIN_CAPABILITIES`.
- Suíte completa: **218 passed, 6 skipped** (os skips são PostgreSQL/MinIO
  condicionais). `compileall` e `ruff check --select I,F,E9` limpos.
- Não executado: validação no Discord. O roteiro T-01 a T-07 de
  `docs/tickets-v2-acceptance.md` continua pendente e agora é executável —
  antes deste fix nem começava, porque o módulo nunca provisionava.

## Próximo passo

Publicar a configuração num servidor de teste pela Central e rodar T-01 a T-07.
Nada aqui autoriza deploy em produção.
