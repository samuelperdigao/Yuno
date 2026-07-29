# Plano de fundação do Yuno

Objetivo: deixar o Yuno vendável. Não é refatoração por estética — cada item abaixo existe porque bloqueia a venda, gera ticket de suporte ou impede cobrar por plano.

Decisão de produto vigente: **SaaS na v1, arquitetura preparada para self-host.** Storage atrás de interface, licença atrás de provider. Self-host vira implementar duas classes, não reescrever.

---

## Fase 0 — Fundação (bloqueia tudo o resto)

### 0.1 Registry de módulos — CONCLUÍDO

**Problema:** `bot/yuno_bot/main.py` registra cog e view manualmente no `setup_hook`. Módulo novo edita o core. Não há como ligar/desligar módulo por plano.

**Solução:** cada módulo declara o que é, em `commands/<mod>/__init__.py`:

```python
MODULE = ModuleSpec(
    key="set",
    cogs=(SetCog,),
    views=(SetPanelView,),
    setup_channels=(
        SetupChannel("set_solicitar", "set-solicitar", "operacao", ("set.solicitar",)),
        SetupChannel("set_aprovacao", "set-aprovacao", "admin", ("set.aprovar", "set.reprovar")),
    ),
    log_channel="logs-set",
    dashboard=DashboardSpec(icon="🎮", nome="Sistema de Set", campos=[...]),
    plano_minimo="basico",
)
```

`setup_hook` descobre por `pkgutil.iter_modules` e itera. `server_setup.py`, o `MODULES` do backend e o dashboard passam a ser **derivados** do registry — hoje a mesma lista está duplicada em três lugares e sai de sincronia.

**Ganho:** módulo novo = uma pasta. Zero edição de core. Habilita plano por módulo.

**Entregue:** `bot/yuno_bot/modules.py` (`ModuleSpec`, `SetupChannel`, `DashboardField`, `ModuleContext`, `discover_modules`, `load_modules`); os 9 módulos declarados nos respectivos `__init__.py`; `main.py` e `server_setup.py` derivando do registry; `backend/tests/test_module_registry.py` travando as invariantes. Paridade verificada — 9 cogs e 7 views persistentes, igual ao registro manual anterior. A divergência real corrigida: `farm_tickets` existia em `schemas.MODULES` e faltava no setup do bot, então nunca aparecia na config das guilds.

### 0.2 Setup idempotente por ID — CONCLUÍDO

**Problema:** `server_setup.py:_find_text_channel` procura canal **por nome**. Cliente renomeia `#metas-semanais` → próximo `/yuno configurar` cria duplicado.

**Solução:** resolver por ID salvo em `settings.discord_setup.channel_ids`. Criar só quando o ID não resolve mais no servidor. `/yuno configurar` vira idempotente e seguro de rodar quantas vezes quiser.

Incluir `/yuno diagnostico`: lista o que está configurado, o que falta, quais permissões o bot não tem. **Isso corta a maior parte dos tickets de suporte antes de existirem.**

**Entregue:** `ensure_setup_channels(guild, config)` resolve por ID salvo → adota canal de mesmo nome (migração de quem já configurou) → cria só em último caso. Retorna `SetupResult` com `created` / `adopted` / `reused`. `diagnostics.py` novo, com `diagnose()` puro e `diagnostic_embed()`. `/yuno diagnostico` cobre licença, permissões do bot, canais e módulos ligados. 13 testes em `test_setup_idempotente.py`.

**Decisão de produto embutida:** canal movido de categoria pelo cliente **não** é movido de volta. O código antigo forçava `channel.edit(category=...)` a cada execução, ou seja, desfazia a organização do servidor do cliente toda vez. Identidade do canal agora é o ID; nome e posição são dele.

**Ganho colateral:** `/yuno configurar` caiu de 2 chamadas HTTP para 1 — o 403 do `get_guild_config` já significa licença inativa, então a chamada extra a `validate_license` era redundante.

### 0.3 Cache de guild config — CONCLUÍDO

**Problema:** `send_module_log` e `send_to_setup_channel` chamam `get_guild_config` cada um. Uma ação simples = 2-3 round-trips HTTP.

**Solução:** `GuildConfigCache` com TTL de 60s por `guild_id`, invalidado no `save_guild_config`. Injetado no `YunoBot`, consumido por `shared.py` e `guards.py`.

**Ganho:** latência de interação cai para 1 round-trip. Em escala, é a diferença entre o bot responder e o Discord dar timeout de 3s.

**Entregue:** `bot/yuno_bot/cache.py` com `TTLCache` genérico (TTL, lock por chave, stats). O cache mora **dentro do `YunoAPI`**, não numa camada acima: há 20 call sites lendo `api.get_guild_config` direto, incluindo views e modals que não recebem o bot — cache por fora exigiria editar todos e bastaria esquecer um. `save_guild_config` popula o cache com a resposta do PUT. TTL configurável (`guild_config_cache_ttl`, default 30s). `get_guild_config(force=True)` para `/yuno diagnostico`. 11 testes em `test_cache.py`.

**Medido:** ação típica (comando lê config → `send_module_log` lê → `send_to_setup_channel` lê) caiu de 3 chamadas para 1 — 67% menos tempo gasto buscando config. Pico de 20 cliques simultâneos no mesmo painel: 1 chamada, não 20 (lock por chave).

**Decisões:**
- **Erro não é cacheado.** Instabilidade momentânea da API viraria 30s de indisponibilidade para o cliente.
- **TTL curto por um motivo específico:** alteração feita no dashboard web não invalida o cache deste processo. O TTL é o tempo máximo que o cliente espera para ver a mudança refletida no bot. Invalidação cross-process via Redis pub/sub (o Redis já está no compose) é o caminho quando isso incomodar — hoje não justifica.
- **Não mexi no cliente HTTP.** Cada método de `api_client.py` ainda faz `async with httpx.AsyncClient(...)`, o que descarta o pool de conexões e refaz handshake TCP a cada request. É um problema real, mas é de transporte, não de cache — misturar as duas mudanças dificultaria isolar regressão. Virou débito.

### 0.4 Guard de módulo em views — CONCLUÍDO

**Problema:** `check_permission` valida `modules` no backend, mas botões de painel não passam por ele. Módulo desligado continua clicável.

**Solução:** decorator `@requires_module(modulo, comando)` em `bot/yuno_bot/guards.py`, chamando o mesmo `ensure_allowed` dos slash commands (módulo + licença + cargo/canal/categoria) antes do callback do botão, com a resposta padronizada de `deny`.

**Levantamento antes de aplicar:** três das sete views já guardavam módulo — `SetPanelView`/`SetApprovalView` e `MetaPanelView` chamavam `ensure_allowed` inline, `ParceriaPanelView` passa por `can_manage_parcerias` (que também checa `check_permission`). As sem guard nenhum eram `AusenciaPanelView`, `RadioPainelView`, `FarmPanelView` e `FarmTicketControlView` — 9 botões ao todo, incluindo os únicos pontos de entrada de farm ticket (não há slash command equivalente para a maioria das ações).

**Decisão que revisou a decisão original:** a proposta inicial era padronizar todas as views para `self.api`. Investigando o código, `FarmPanelView`/`FarmTicketControlView` guardam `self.controller` — a instância do `FarmTicketsCog`, com dezenas de métodos de domínio, não um `YunoAPI`. Renomear teria sido enganoso. O decorator resolve isso lendo `self.api` quando existe e caindo para `self.controller.bot.api` caso contrário — sem exigir renomear nada.

**Achado colateral:** `/radio alterar` (slash command, não só o botão do painel) nunca checou módulo nem licença — só um cargo customizado. Não corrigido nesta sessão (fora do escopo de "views"); vira item 7 dos débitos técnicos.

**Entregue:** `requires_module` em `guards.py`; aplicado em `ausencia/views.py`, `radio/views.py`, `farm_tickets/views.py` (2 classes, 9 botões); `set/views.py` e `meta/views.py` migrados do `ensure_allowed` inline para o decorator. 3 testes novos em `backend/tests/test_view_guard.py` cobrindo módulo desligado (nega e não chama o callback), módulo ligado (chama) e extração do `api` via `controller.bot.api`. 67 testes passando.

### 0.5 Alembic — CONCLUÍDO

**Problema:** sem migração versionada, a segunda atualização em produção quebra o banco de cliente. `db.py` já tinha um sintoma disso: `_ensure_compat_columns` fazia `ALTER TABLE` manual via SQL cru porque `Base.metadata.create_all` não altera tabela existente.

**Solução:** `alembic init -t async migrations` (o template async casa com o `create_async_engine` que o projeto já usa). `migrations/env.py` importa `app.models` e lê a URL de `get_settings().database_url` — a mesma fonte que a aplicação usa em runtime, nunca duplicada em `alembic.ini`.

**O problema real de introduzir Alembic com produção já rodando:** a baseline não podia refletir o `models.py` atual (que já tem as colunas de pasta de membro do farm ticket, ver 0.1) porque a produção real ainda está no schema *anterior* a essas colunas — gerar a baseline do estado atual faria `alembic upgrade head` tentar `CREATE TABLE` em cima de tabelas que já existem e derrubar o próximo deploy. Duas migrações, então: **baseline** = schema tal como está hoje em produção (sem as colunas de pasta), **segunda migração** = `add_column` das 4 colunas de pasta, autogerada comparando a baseline aplicada contra o `models.py` atual. Efeito final idêntico ao `_ensure_compat_columns`, só que versionado.

**Adoção do banco de produção:** `create_database()` (chamada no `lifespan` do FastAPI, como já era) inspeciona o banco antes de migrar. Sem `alembic_version` mas com a tabela `licenses` já existindo = banco antigo, criado por `create_all` antes do Alembic existir → `alembic stamp` na baseline (marca como já aplicada, sem reexecutar `CREATE TABLE`) e só então `upgrade head`, que roda de verdade só a migração das colunas de pasta. Testado simulando esse cenário exato (schema pré-Alembic → `create_database()` → schema completo, `alembic_version` na head). Banco novo (dev, teste, cliente novo) não tem `licenses` nem `alembic_version` → pula o stamp e roda as duas migrações do zero, resultado idêntico.

**Regra daqui pra frente: toda alteração em `models.py` vem com migração no mesmo commit** (`alembic revision --autogenerate -m "..."`, revisar o arquivo gerado, testar `upgrade`+`downgrade` antes de commitar).

**Nota de deploy:** o próximo `deploy.yuno.ps1` contra o servidor Oracle é a primeira vez que esse caminho de adoção roda contra o banco de produção de verdade — foi testado contra uma simulação fiel (mesmo schema, mesma ausência de `alembic_version`), não contra o banco real. Vale rodar com backup do Postgres em mãos.

**Entregue:** `backend/alembic.ini`, `backend/migrations/` (`env.py` configurado, 2 migrações: `b83c59e0158e` baseline e `d4b265e2fb2a` colunas de pasta), `app/db.py` reescrito (`_ensure_compat_columns` removido, `create_database()` agora roda `stamp`+`upgrade` via Alembic), `alembic==1.18.5` em `requirements.txt`, `Dockerfile` copiando `alembic.ini` e `migrations/` para a imagem. 67 testes passando (sem teste novo — é infraestrutura de schema, verificado manualmente com os dois cenários acima).

### 0.6 Abstração de storage e licença — CONCLUÍDO

**`Repository`/`LicenseProvider`:** `bot/yuno_bot/interfaces.py` declara `GuildConfigRepository` (`get_guild_config`/`save_guild_config`) e `LicenseProvider` (`validate_license`) como `typing.Protocol`. `YunoAPI` já satisfaz os dois estruturalmente — nada foi renomeado nem movido, porque Python resolve por estrutura, não por herança: os ~20 call sites que recebem `api` continuam recebendo `YunoAPI`. O valor não é técnico agora, é documental — os dois protocolos nomeiam exatamente o que uma implementação self-host precisaria reimplementar, e ficam sem custo até esse dia chegar. `test_interfaces.py` trava que `YunoAPI` continua satisfazendo os dois (`isinstance` com `@runtime_checkable`).

**Não fiz uma abstração maior que isso.** `YunoAPI` tem 30+ métodos específicos de farm_tickets (débito conhecido) — formalizar um protocolo com essa superfície inteira seria documentar a bagunça, não abstrair. Os dois protocolos cobrem só os dois pontos que o self-host de fato precisa trocar.

**Migração de `parcerias_repository` (SQLite local → backend):** era o item concreto e valioso de 0.6 — o local anterior perdia todo o estado de parcerias a cada redeploy, e quebrava multi-tenant (estado no filesystem do container, não no banco compartilhado). Agora:

- `backend/app/models.py`: `Parceria` e `ParceriaConfig` novas. `nome_familia_normalizado` guarda a versão sem acento/minúscula para unicidade e busca — SQLite tinha `COLLATE NOCASE`, Postgres não tem equivalente direto.
- `backend/app/parceria.py` (lógica) + `backend/app/api/parceria.py` (rotas `/internal/parcerias/*`, mesmo padrão de `farm_tickets`: `require_bot_token` + `assert_license` por guild).
- `bot/yuno_bot/commands/parceria/repository.py` reescrito: mesma classe `ParceriasRepository`, mesmos nomes de método — `cog.py` não mudou uma linha. Por dentro, HTTP em vez de `sqlite3`. Leituras (`get_config`, `find_by_name`, `list_active`, `get`, `name_exists_for_other`) tratam falha de rede/licença como "sem dado" (mesmo comportamento que "não achei a linha" tinha no SQLite); escritas propagam erro — `views.py` ganhou tratamento para `ParceriaDuplicadaError` (409, antes era `sqlite3.IntegrityError`) nos dois pontos que criam/editam.
- Migração Alembic `3795707f5b0a` para as duas tabelas novas.
- `docker-compose.yml`: removido o volume `bot_data` (existia só para o SQLite local que não existe mais). `.env.example`: removido `PARCERIAS_DATABASE_PATH`.

**Achado ao migrar, não corrigido:** as rotas novas de parceria checam licença ativa (`assert_license`) e o fluxo antigo via SQLite nunca checava — o painel de parcerias funcionava mesmo sem licença. Isso é uma correção de produto (parceria agora se comporta como todo módulo licenciado), não uma regressão, mas é uma mudança de comportamento real que vale testar num servidor com licença revogada antes do próximo deploy.

**Achado que exigiu depuração:** `Parceria.updated_at` com `onupdate=func.now()` quebrava com `MissingGreenlet` ao ser lido de volta na mesma resposta HTTP — SQLAlchemy async tenta um refresh lazy fora do contexto async ao acessar um atributo que só o banco calculou. `FarmTicket.updated_at` tem o mesmo `onupdate` e nunca deu esse erro porque nenhuma resposta o serializa de volta. Corrigido setando `updated_at` explicitamente em Python (`app/parceria.py`), não via `onupdate`. Vale desconfiar do mesmo padrão em qualquer coluna nova que precise ser lida na mesma request em que foi escrita.

**Entregue:** 70 testes passando (3 novos: `test_interfaces.py`, mais os de `test_api.py` para `/internal/parcerias/*`, mais a reescrita do teste de `ParceriasRepository` em `test_bot_modal_helpers.py` para cobrir tradução de erro HTTP em vez do ciclo de vida do SQLite).

---

## Fase 1 — Dashboard dentro do Discord — CONCLUÍDO (com escopo revisado)

**O item mais rentável da lista.** A premissa original era que o cliente precisava sair do Discord pra configurar. Investigando antes de portar `cogs/dashboard.py` do MDM, essa premissa se mostrou errada: **todo módulo já tem um comando de painel funcionando dentro do Discord**, com seletor nativo (`/set painel <canal> <canal> <cargo> <cargo>`, `/meta painel`, `/radio painel`, `/parceria setup_parcerias`, `/setup_farm_tickets`, `/setup_ausencia`), e alguns têm efeito colateral além de salvar dado — `/set painel` também tranca visibilidade de canal pra membro novo. Portar o padrão do MDM (modal genérico gerado por campo, reescrevendo a lógica de cada sistema) teria custo escondido real: duplicar ou perder esses efeitos colaterais, sem meio de testar contra um Discord de verdade pra pegar a regressão.

**Escopo entregue, confirmado com o dono antes de escrever código:** o painel é um board de status + atalho pro comando certo, não um editor. `/yuno painel` publica uma mensagem Components V2 (payload cru — a versão de discord.py do projeto, 2.4, não tem `discord.ui.LayoutView`; mesmo padrão já provado em produção no MDM) listando os 9 módulos do registry, cada um com ✅ configurado / ⚠️ incompleto / ⛔ desligado. O botão **≡** de cada módulo abre uma resposta efêmera com os valores atuais e, se incompleto, qual comando roda (`Rode /set painel para completar a configuração`).

**Sem CTA de upgrade de plano** (decisão tomada antes de começar): não existe hoje nenhum campo de plano em `License`/`GuildConfig`, só `plano_minimo` declarado no registry sem ligação com nada. Registrado como débito técnico.

**O trabalho real não foi a UI, foi auditar `dashboard_fields` de cada módulo contra onde o dado realmente mora** — a metadata tinha sido escrita durante o 0.1 (criação do registry) e nunca validada contra código real, porque nada a consumia ainda:

- `meta`: campo declarado `manager_role_ids` (lista) não existe — o campo real é `allowed_role_id` (singular). Corrigido.
- `ausencia`: campo declarado `panel_channel_id` não existe — o real é `canal_ausencias_id`. Corrigido.
- `radio`, `encomenda`, `producao`, `ticket`: declaravam um campo de cargo (`manager_role_ids`/`staff_role_ids`) que **não corresponde a nenhuma funcionalidade real** — `/radio alterar` restringe por nome de cargo contendo "gerente" (hardcoded, não configurável); `encomenda`/`producao`/`ticket` nunca tiveram comando de restrição por cargo. Campos removidos da declaração em vez de fingir uma configuração que não existe. Vira item de débito técnico (nenhum dos quatro tem como restringir por cargo hoje).
- `farm_tickets`: achado um **bug real, não só de metadata** — `participant_role_ids` é obrigatório pra alguém conseguir abrir ticket (`member_has_any_role` contra lista vazia nunca autoriza ninguém), mas `/setup_farm_tickets` hardcodeava `[]` e não tinha parâmetro pra isso. Corrigido: novo parâmetro `cargos_participantes` no comando.
- `parceria`: campo declarado `panel_channel_id` não existe no model — o real é `registrar_channel_id`. Corrigido. Também não espelhava resumo em `guild_config.settings.parceria` (farm_tickets já fazia isso desde a criação); adicionado, é o que permite o painel ler o estado de parceria sem saber que ela tem tabela própria.

**Canal do painel:** novo `CORE_CHANNEL` (`yuno-painel`, categoria admin), criado automaticamente por `/yuno configurar` como `yuno-logs` já era — não precisa de comando de setup próprio.

**Entregue:** `bot/yuno_bot/dashboard.py` (cálculo de estado, payload V2, view dispatcher persistente, `show_module_info`), `/yuno painel` em `main.py`, `CORE_CHANNELS` com `painel`. 83 testes passando (13 novos em `test_dashboard.py`, cobrindo cálculo de estado e leitura de valores — a parte que não é só payload).

---

## Fase 2 — Port do núcleo genérico

Ordem, do que ensina o padrão para o que exige mais cuidado:

| # | Módulo | Origem MDM | LOC origem | Por que nessa posição |
|---|---|---|---|---|
| 1 | ~~`adv`~~ | `cogs/adv.py` | 309 | **CONCLUÍDO.** Pequeno; exercita painel + modal + log ponta a ponta |
| 2 | ~~`anuncio`~~ | `cogs/anuncio.py` | 335 | **CONCLUÍDO.** Cargos anunciantes exercitam `command_permissions` |
| 3 | `hierarquia` | `cogs/hierarquia.py` | 335 | Manipulação de cargo; exercita permissão do bot |
| 4 | `membros` | `cogs/membros.py` | 190 | Primeiro módulo sem slash command (listeners) |
| 5 | `acao` | `cogs/acao.py` + `acao_painel.py` | 1223 | Maior; padrão já consolidado |
| 6 | `mod` | `cogs/mod.py` | 252 | Trivial, fecha a fase |
| 7 | `disparo` | `cogs/disparo.py` | 545 | Rate limit exige cuidado; por último |

Fora do escopo desta fase, por serem específicos da facção: `bau`, `colete`, `recolhimento`, `heroina`, e o `farm` de itens ilegais.

### `adv` — CONCLUÍDO

Portado sem tabela nova: cabe inteiro em `SystemRecord` (`module="adv"`, `payload={membro_id, descricao, dias}`), seguindo a regra do checklist ("registro simples, sem query analítica → `SystemRecord`, prefira isso"). Zero migração, zero rota nova no backend — só a chave `adv` em `MODULES`.

**Divergências propositais do MDM:** os comandos legados do MDM (`/setup-adv` configurando canal via parâmetro, `/adv` como atalho direto) não foram portados — o Yuno já resolve "onde fica o canal" via `setup_channels`/`/yuno configurar`, então existir um segundo jeito de configurar seria a mesma inconsistência que a Fase 1 encontrou em outros módulos. Permissão trocou de `manage_guild` hardcoded para `ensure_allowed("adv", "aplicar")` (módulo + `command_permissions`), consistente com todo o resto do Yuno em vez de um cargo fixo do Discord.

**Entregue:** `bot/yuno_bot/commands/adv/` completo (`cog.py`, `embeds.py`, `modals.py`, `views.py`, `__init__.py`), `MODULE` registrado (`ordem=90`), `adv` em `_SIMPLE_MODULES`/`_COMMAND_HINTS` do dashboard (Fase 1). 84 testes passando.

### `anuncio` — CONCLUÍDO

Este era o módulo escolhido pelo plano justamente para exercitar `command_permissions` de verdade — e ao portar ficou claro por quê: é o **primeiro módulo do Yuno com um comando dedicado só para configurar cargo autorizado**, distinto do canal. `encomenda`/`producao`/`ticket`/`radio` nunca tiveram isso (débito técnico já registrado); `set`/`meta` configuram cargo mas dentro do próprio comando de painel, junto com outros campos. `anuncio` segue o mesmo padrão de `set painel`/`meta painel`: `/anuncio painel <canal> <cargos_anunciantes>` publica o painel (editando em vez de duplicar se já existir, igual aos outros) e grava `command_permissions["anuncio.publicar"]` — o guard genérico (`ensure_allowed`) passa a fazer todo o trabalho de "quem pode", sem checagem de cargo hardcoded no código do módulo.

**Simplificação em relação ao MDM:** como `command_permissions["anuncio.publicar"].channel_ids` já restringe o comando/botão ao canal configurado, o próprio `interaction.channel` pode ser usado como destino do anúncio — não precisa resolver o canal de novo via `settings` em `views.py`. O MDM resolvia isso com uma função `db_get_anuncio_canal` chamada toda vez.

**Divergência proposital:** o bypass de administrador do MDM (`if member.guild_permissions.administrator: return True`, ignorando a lista de cargos) não foi portado — o Yuno já tem seu próprio conceito de admin (`admin_role_ids` da guild config, checado dentro do `check_permission` do backend) e replicar o bypass do Discord aqui seria inconsistente com todo o resto do produto, que não faz essa checagem em nenhum outro módulo.

**Entregue:** `bot/yuno_bot/commands/anuncio/` completo, incluindo o fluxo de anexo opcional (espera de 60s por mensagem com arquivo, igual ao original). `anuncio` em `MODULES`, registry (`ordem=100`) e `_COMMAND_HINTS` do dashboard. 85 testes passando.

---

## Fase 3 — Farm genérico (módulo premium)

O farm do MDM (`farm.py` 1707 + `farm_painel` + `farm_relatorio` + `farm_advertencias` = ~4000 LOC) é a feature mais completa e mais difícil de generalizar: os itens (`folha`, `opio`, `seringa`, `agulha`) são **colunas literais** nas tabelas `metas`, `progresso` e `eventos`.

Generalização: catálogo de itens por servidor (`Product` já existe), meta como lista de `{item_id, quantidade}` (já é assim em `FarmWeeklyGoal.items`), progresso como JSON. O Yuno já tem o modelo certo — falta portar a lógica de ranking, relatório e advertência automática.

Justifica ser plano premium.

---

## Fase 4 — Acabamento comercial

- `messages` consumido de fato: cliente edita textos e cores dos embeds
- Validação de licença com cache curto em todos os comandos (revogação com efeito em ≤5min)
- Onboarding guiado: ao entrar no servidor, o bot manda DM ao dono com os 3 passos
- Página de status e changelog público
- Backup automatizado e restore testado

---

## Sequenciamento

Fase 0 é bloqueante — cada módulo portado antes dela carrega o setup frágil e o hardcode do `main.py`, e o retrabalho depois é proporcional ao número de módulos já portados.

Fase 1 pode começar assim que 0.1 (registry) estiver de pé, porque o dashboard consome o registry.

**Ordem de execução: ~~0.1~~ ~~0.2~~ ~~0.3~~ ~~0.4~~ ~~0.5~~ ~~0.6~~ ~~Fase 1~~ (feitos) → Fase 2.**

---

## Critério de pronto para vender

- [ ] Servidor Discord limpo → convite do bot → `/yuno configurar` → `/yuno painel` → tudo funcionando em menos de 10 minutos, sem ajuda
- [ ] `/yuno diagnostico` aponta qualquer configuração faltante em linguagem que o cliente entende
- [ ] Nenhum comando quebra com traceback visível ao usuário
- [ ] Painéis sobrevivem a deploy
- [ ] Licença revogada bloqueia o bot em ≤5 minutos
- [ ] Migração de banco testada com dados reais
- [ ] Rollback de deploy documentado e testado
