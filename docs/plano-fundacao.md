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

### 0.5 Alembic

Sem migração versionada, a segunda atualização em produção quebra o banco de cliente. `alembic init`, baseline do schema atual, e a regra: **toda alteração em `models.py` vem com migração no mesmo commit.**

### 0.6 Abstração de storage e licença

`Repository` (protocolo) com implementação `ApiRepository` hoje. `LicenseProvider` com `RemoteLicenseProvider` hoje. É o que preserva a opção de self-host sem custo agora.

Junto: migrar `parcerias_repository` do SQLite local para o backend. Hoje o estado de parcerias some no redeploy.

---

## Fase 1 — Dashboard dentro do Discord

**O item mais rentável da lista.** Hoje o cliente compra, entra no Discord, e para configurar precisa sair, abrir navegador, logar com OAuth. Metade desiste ali.

Base: `cogs/dashboard.py` do Morro do Mineiro (Components V2, `Section` + `accessory`, paginado, modal por sistema). O padrão está certo. O que muda:

- Lista de sistemas **gerada pelo registry**, não hardcoded
- Persistência via `PUT /guilds/{id}/config`, não SQLite
- `DASHBOARD_CHANNEL_ID` sai; o canal vem do setup
- Módulos fora do plano aparecem bloqueados com CTA de upgrade — **o dashboard vira canal de venda**
- Cada sistema mostra estado: configurado / incompleto / desligado

Comando: `/yuno painel`. Publica um painel persistente no canal de administração.

---

## Fase 2 — Port do núcleo genérico

Ordem, do que ensina o padrão para o que exige mais cuidado:

| # | Módulo | Origem MDM | LOC origem | Por que nessa posição |
|---|---|---|---|---|
| 1 | `adv` | `cogs/adv.py` | 309 | Pequeno; exercita painel + modal + log ponta a ponta |
| 2 | `anuncio` | `cogs/anuncio.py` | 335 | Cargos anunciantes exercitam `command_permissions` |
| 3 | `hierarquia` | `cogs/hierarquia.py` | 335 | Manipulação de cargo; exercita permissão do bot |
| 4 | `membros` | `cogs/membros.py` | 190 | Primeiro módulo sem slash command (listeners) |
| 5 | `acao` | `cogs/acao.py` + `acao_painel.py` | 1223 | Maior; padrão já consolidado |
| 6 | `mod` | `cogs/mod.py` | 252 | Trivial, fecha a fase |
| 7 | `disparo` | `cogs/disparo.py` | 545 | Rate limit exige cuidado; por último |

Fora do escopo desta fase, por serem específicos da facção: `bau`, `colete`, `recolhimento`, `heroina`, e o `farm` de itens ilegais.

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

**Ordem de execução: ~~0.1~~ ~~0.2~~ ~~0.3~~ ~~0.4~~ (feitos) → 0.5 → 0.6 → Fase 1 → Fase 2.**

---

## Critério de pronto para vender

- [ ] Servidor Discord limpo → convite do bot → `/yuno configurar` → `/yuno painel` → tudo funcionando em menos de 10 minutos, sem ajuda
- [ ] `/yuno diagnostico` aponta qualquer configuração faltante em linguagem que o cliente entende
- [ ] Nenhum comando quebra com traceback visível ao usuário
- [ ] Painéis sobrevivem a deploy
- [ ] Licença revogada bloqueia o bot em ≤5 minutos
- [ ] Migração de banco testada com dados reais
- [ ] Rollback de deploy documentado e testado
