# Handoff — continuar o Yuno no Claude Code

Documento de retomada. Cole isto (ou peça para ler `docs/HANDOFF.md`) ao abrir o Claude Code no repositório `Yuno`.

Data: 2026-07-29 · Branch `main` · Último commit do repositório: `162d80d`

---

## 0. Antes de qualquer coisa: commitar

**Nada do que está descrito aqui foi commitado.** O working tree tem duas frentes empilhadas: trabalho seu anterior e a fundação nova. Se algo quebrar, não há ponto de retorno e não dá para separar a causa.

### Frente A — sua, já existia antes desta sessão (313 linhas)

Feature de **pastas de membro nos farm tickets**: `folder_channel_id`, `folder_slot`, `game_id`, `folder_nickname`.

```
backend/app/models.py                          +4    colunas novas em FarmTicket
backend/app/schemas.py                         +9    campos nos schemas + open_payload
backend/app/db.py                             +21    _ensure_compat_columns (ALTER TABLE manual)
backend/app/farm_tickets.py                   +34
backend/app/api/farm_tickets.py                +9
bot/yuno_bot/commands/farm_tickets/helpers.py +177   MemberFolderIdentity, resolve_member_folder, next_folder_slot
bot/yuno_bot/commands/farm_tickets/cog.py     +37
bot/yuno_bot/commands/farm_tickets/embeds.py  +26
bot/yuno_bot/commands/farm_tickets/views.py   +10
deploy.yuno.ps1                                +2
```

Confira antes de commitar — não sei o estado em que você parou.

```bash
git add backend/app bot/yuno_bot/commands/farm_tickets/cog.py \
        bot/yuno_bot/commands/farm_tickets/embeds.py \
        bot/yuno_bot/commands/farm_tickets/helpers.py \
        bot/yuno_bot/commands/farm_tickets/views.py deploy.yuno.ps1
git commit -m "feat(farm-tickets): pastas de membro com slot, game id e apelido"
```

### Frente B — fundação 0.1 a 0.3

```bash
git add bot/yuno_bot backend/tests docs .claude
git commit -m "feat(core): registry de modulos, setup idempotente por ID e cache de guild config"
```

`.claude/` está untracked. Se não commitar, a skill `yuno-dev` fica só na sua máquina e some se você clonar o repo em outro lugar.

---

## 1. Contexto do produto

Yuno é um **produto vendido**, não um bot pessoal. O critério que decide toda discussão técnica: *o cliente consegue configurar isso sozinho, em menos de 10 minutos, sem abrir ticket?*

**Decisões tomadas nesta sessão:**

- **Distribuição: SaaS na v1, arquitetura preparada para self-host.** Você pediu híbrido; recusei para a v1. Self-host exigiria heartbeat de licença, ofuscação, storage local e um segundo pipeline de suporte — antes do primeiro cliente pago, e com o custo de toda dúvida virar "é o Yuno ou é o ambiente dele?". A opção fica preservada por design (storage e licença atrás de interface, item 0.6 do plano), não por implementação.
- **Escopo do port MDM → Yuno: só o núcleo genérico.** Fora: `bau`, `colete`, `recolhimento`, `heroina` e o `farm` de itens ilegais — são específicos da sua facção.
- **Ordem: fundação antes de portar features.** Cada módulo portado sobre a base antiga multiplicaria o retrabalho.

Detalhe completo em `docs/plano-fundacao.md`.

---

## 2. O que foi feito

Estado: **64 testes passando**, 30 slash commands, 9 cogs, 7 views persistentes.

### 0.1 Registry de módulos — `bot/yuno_bot/modules.py`

Cada módulo se declara no próprio `__init__.py` com `MODULE = ModuleSpec(...)`. `main.py` e `server_setup.py` **não são mais editados** para adicionar módulo — as listas de cogs, views, canais de setup, canais de log e chaves de módulo são derivadas do registry.

`cogs` e `views` recebem **fábricas**, não classes, porque as dependências divergem: a maioria só precisa do bot, `parceria` precisa do repositório, e as views de `farm_tickets` precisam da instância do cog (`ctx.cog(FarmTicketsCog)`). O loader cria todos os cogs antes de qualquer view.

**Bug real que isso corrigiu:** `farm_tickets` estava em `backend/app/schemas.MODULES` e faltava na lista do bot. Consequência — o módulo nunca aparecia em `modules` da guild config, ou seja, **nenhum cliente conseguiria ligar ou desligar o farm ticket**. `test_module_registry.py` impede a divergência de voltar.

### 0.2 Setup idempotente por ID — `server_setup.py` + `diagnostics.py`

Reconciliação em três níveis: **ID salvo em `settings.discord_setup` → canal de mesmo nome (adoção) → criar**. O nível do meio faz servidores já configurados migrarem sem duplicar nada.

**Decisão de produto embutida:** canal movido de categoria pelo cliente **não** é movido de volta. O código antigo chamava `channel.edit(category=...)` a cada execução — desfazia a organização do servidor do cliente toda vez. Identidade do canal agora é o ID; nome e posição são dele.

`/yuno diagnostico` novo: licença, permissões do bot com o motivo em português, contagem de canais, módulos desligados. `diagnose()` é função pura — testável sem subir bot.

**Ganho colateral:** `/yuno configurar` caiu de 2 chamadas HTTP para 1. O 403 do `get_guild_config` já significa licença inativa, então a chamada a `validate_license` era redundante.

### 0.3 Cache de guild config — `cache.py`

`TTLCache` genérico com lock por chave. Mora **dentro do `YunoAPI`**, não em camada acima: há 20 call sites lendo `api.get_guild_config` direto, e views e modals recebem o `api`, não o bot.

Medido com 30ms de round-trip:

| Cenário | Antes | Depois |
|---|---|---|
| Ação típica (3 leituras) | 3 chamadas, 91ms | 1 chamada, 30ms |
| 20 cliques simultâneos no painel | 20 chamadas | 1 chamada |

Erro não é cacheado. TTL 30s, configurável por `guild_config_cache_ttl`.

### Arquivos novos

```
bot/yuno_bot/modules.py                     registry declarativo
bot/yuno_bot/cache.py                       TTLCache
bot/yuno_bot/diagnostics.py                 diagnose() puro + embed
backend/tests/test_module_registry.py       8 testes
backend/tests/test_setup_idempotente.py    13 testes
backend/tests/test_cache.py                11 testes
docs/plano-fundacao.md                      plano completo, com estado por etapa
.claude/skills/yuno-dev/                    skill + 3 referências
```

### Arquivo alterado que merece atenção

`backend/tests/test_bot_modal_helpers.py` — havia um teste frágil afirmando `log_channel_ids["producao"] == "107"`, índice posicional. Quebrou quando `farm_tickets` entrou no meio da ordem. Reescrevi para derivar do registry.

---

## 3. Próximo passo: 0.4 — guard de módulo em views

**Problema:** `check_permission` (backend) valida `modules` corretamente, e os slash commands passam por ele via `ensure_allowed`. Mas **botões de painel não passam por lugar nenhum**. Um módulo desligado no dashboard continua com os botões clicáveis, o formulário abre e o registro é criado. Para um produto que vende plano por módulo, isso é o buraco que permite usar o que não foi pago.

**Solução proposta:** decorator `@requires_module("<key>")` aplicável a callback de botão e de view, com a mesma resposta padronizada de `deny`. A config já está cacheada (0.3), então o custo é ~zero.

**Onde aplicar** — as 7 views persistentes: `SetPanelView`, `MetaPanelView`, `AusenciaPanelView`, `ParceriaPanelView`, `RadioPainelView`, `FarmPanelView`, `FarmTicketControlView`.

**Ponto de atenção:** o decorator precisa funcionar em `discord.ui.button` callbacks, que recebem `(self, interaction, button)`. Extrair o `api` de `self` exige convenção — todas as views hoje guardam `self.api` ou `self.controller`. Vale checar antes de escolher a assinatura.

**Sugestão de teste:** módulo desligado → clique no botão responde `deny` e **não** cria registro. É o teste que prova o valor comercial.

---

## 4. O que ainda não foi validado

Sendo direto sobre o limite do que foi feito: **nada disso rodou contra Discord real nem contra Postgres real.** Tudo foi provado com teste e dublê. No Claude Code você tem Docker e terminal de verdade — vale fazer antes de seguir para 0.4:

1. `docker compose up --build` e conferir que o bot sobe com o registry.
2. Convidar o bot num servidor Discord limpo.
3. `/yuno configurar` → conferir a estrutura criada.
4. `/yuno configurar` de novo → **não pode criar nada**. É a prova de idempotência em produção.
5. Renomear um canal, rodar de novo → não pode duplicar.
6. `/yuno diagnostico` → conferir se o texto faz sentido para quem não é você.

---

## 5. Débitos técnicos, em ordem de impacto na venda

1. **Não há dashboard de configuração dentro do Discord.** Maior gap de UX e item mais rentável. O cliente compra, entra no Discord e precisa sair para o navegador com OAuth. Base pronta no MDM: `cogs/dashboard.py` (Components V2, `Section` + `accessory`, paginado). O registry já expõe `dashboard_fields`, `icon`, `nome`, `descricao` — a UI pode ser gerada dele.
2. **Nenhum botão de painel verifica `modules`.** É o 0.4.
3. **`parcerias_repository` grava SQLite local no container do bot.** Quebra o multi-tenant; o estado some no redeploy.
4. **`api_client.py` tem 30+ métodos de farm_tickets.** Domínio vazando para a camada de transporte.
5. **`_apply_set_visibility` (em `set/cog.py`) itera todas as categorias e todos os canais chamando `set_permissions`.** Em servidor com 80 canais é rate-limit garantido, travando o setup na frente do cliente. Não foi tocado nesta sessão.
6. **Sem Alembic.** Você já está sentindo isso: `backend/app/db.py` ganhou um `_ensure_compat_columns` com `ALTER TABLE` manual para SQLite e Postgres. Funciona, mas é migração improvisada e não versionada — na terceira coluna nova vira problema sério.
7. **`messages` não é consumido.** Cliente não consegue mudar nenhum texto do bot.
8. **Licença só é validada em 3 comandos.** Revogação não tem efeito imediato nos demais.
9. **Cada método de `api_client.py` abre um `httpx.AsyncClient` novo.** Descarta o pool e refaz handshake TCP a cada request. Deve ser cliente persistente.
10. **`guild_config` sofre race de read-modify-write.** Vários cogs leem a config inteira, alteram um ramo e dão PUT do documento todo — duas alterações concorrentes e a última apaga a outra. **Já existia antes do cache, não é regressão.** Correção: PATCH por caminho.
11. **Alteração no dashboard web só reflete no bot após o TTL** (30s). Redis pub/sub resolve; o Redis já está no compose.

---

## 6. Coisas que vão te morder no Claude Code

**`backend/tests/test_api.py` falha com `PermissionError`.** Ele faz `unlink` de um `.db` na raiz, e o OneDrive segura o arquivo. **Não é código** — confirmei rodando o repo copiado para fora do OneDrive: 64/64 passam. Mova o repo para um caminho local ou apague o `.db` antes.

**A skill `yuno-dev` já funciona no Claude Code.** Está em `.claude/skills/yuno-dev/`, que o Claude Code lê automaticamente. Ela carrega o mapa dos dois repositórios, o padrão de módulo e os débitos — evita reler 30k linhas a cada sessão. As referências ficam em `.claude/skills/yuno-dev/references/`:

- `mapa-yuno.md` — inventário de arquivos, tabelas, contratos
- `mapa-mdm.md` — inventário do Morro do Mineiro e o que vale portar
- `port-checklist.md` — roteiro de port MDM → Yuno

**Mantenha a skill viva.** Quando a arquitetura mudar, atualize o arquivo de referência correspondente no mesmo commit. Se ela envelhecer, a próxima sessão paga o custo de redescobrir tudo.

---

## 7. Comandos úteis

```bash
# suite completa
python -m pytest backend/tests -q

# só a fundação
python -m pytest backend/tests/test_module_registry.py \
                 backend/tests/test_setup_idempotente.py \
                 backend/tests/test_cache.py -q

# verificações de higiene multi-tenant
grep -rnP '\b\d{17,20}\b' bot/yuno_bot backend/app --include="*.py"   # IDs hardcoded: deve vir vazio
grep -rn "sqlite3" bot/yuno_bot --include="*.py"                       # só parceria (débito #3)

# inspecionar o registry sem subir o bot
cd bot && python -c "from yuno_bot.modules import discover_modules; \
  [print(f'{s.ordem:>3} {k:<13} {s.plano_minimo:<8} canais={len(s.setup_channels)}') \
   for k,s in discover_modules().items()]"
```

---

## 8. Prompt sugerido para abrir o Claude Code

> Leia `docs/HANDOFF.md` e `docs/plano-fundacao.md`. A skill `yuno-dev` tem o mapa da arquitetura — use antes de ler código. Já commitei o working tree. Quero seguir com a etapa 0.4 (guard de módulo em views). Antes de escrever código, me diga como pretende extrair o `api` dentro do decorator, já que as views têm construtores diferentes.
