---
name: yuno-dev
description: Desenvolvimento do Yuno — bot Discord SaaS multi-tenant para servidores FiveM, vendido por licença. Use SEMPRE que a conversa envolver o repositório Yuno, o bot Morro do Mineiro, portar/migrar funcionalidades entre os dois, criar ou alterar módulos (set, meta, ausência, encomenda, rádio, parceria, ticket, farm, produção, advertência, hierarquia, anúncio), mexer no backend FastAPI de licenças/guild_config, no dashboard React, no setup dentro do Discord, ou discutir arquitetura, precificação técnica e experiência de configuração do cliente. Use também quando o pedido for genérico ("melhorar o bot", "arrumar isso", "adicionar um comando") mas o contexto for um desses dois projetos — a skill carrega o mapa da arquitetura e evita releitura de 30k linhas de código.
---

# Yuno — desenvolvimento do produto

Yuno é um **produto vendido**, não um bot pessoal. Toda decisão técnica responde a uma pergunta comercial: *o cliente consegue configurar isso sozinho, em menos de 10 minutos, sem abrir ticket de suporte?* Se a resposta for não, o código está errado mesmo que funcione.

O outro repositório, **Morro do Mineiro Bot** (MDM), é o bot pessoal do dono — um monólito maduro, testado em produção real, que serve como **banco de features validadas** para o Yuno. Nunca é o destino de código novo. O fluxo é sempre MDM → Yuno, nunca o contrário.

## Antes de qualquer coisa: economia de contexto

Estes repositórios são grandes (Yuno ~8.5k LOC, MDM ~22k LOC). Ler tudo é desperdício e degrada a qualidade da resposta, porque o que importa fica soterrado.

**Nunca leia:** `__pycache__/`, `.pytest_cache/`, `node_modules/`, `dashboard/dist/`, `logs/`, `deprecated/`, `*.db`, `*.pyc`, `.codex-remote-attachments/`.

**Ordem de leitura obrigatória** — pare assim que tiver o suficiente para agir:

1. `references/mapa-yuno.md` e `references/mapa-mdm.md` desta skill. Eles já contêm o inventário de arquivos, responsabilidades e tamanhos. Na maioria das tarefas isso basta para saber *onde* mexer.
2. Só então abra os arquivos específicos que a tarefa toca.
3. Para descobrir onde algo mora, prefira `grep -rn "termo" --include="*.py"` a ler arquivos inteiros. Para listar a superfície de comandos, `grep -oP 'name="\K[^"]+'`.
4. Ao ler um arquivo grande (`db_service.py` tem 2556 linhas, `farm.py` 1707), leia o índice primeiro: `grep -n "^def \|^class \|^async def"`.

Quando você descobrir algo estrutural que não está nos mapas — um débito técnico novo, uma decisão de arquitetura, um arquivo que mudou de papel — **atualize o arquivo de referência correspondente**. A skill é memória de longo prazo; se ela envelhece, a próxima sessão paga o custo de redescobrir.

## Modelo de produto e a regra que dele decorre

Decisão vigente: **SaaS na v1, arquitetura preparada para self-host.** Um bot único hospedado pelo dono, licença lifetime vinculada a `guild_id`. Self-host é plano futuro e não deve custar nada agora além de disciplina de design.

Na prática isso significa uma regra dura: **todo acesso a dado passa por uma abstração, nunca por SQLite direto no processo do bot.** Quando o self-host chegar, trocar o backend deve ser implementar uma classe, não reescrever módulos. Hoje existe uma violação conhecida disso (`parcerias_repository`, ver Débitos).

Consequências práticas do modelo SaaS que precisam estar sempre na cabeça:

- O bot atende **N servidores simultâneos**. Nenhum ID pode ser constante no código. Se você viu um número de 17-20 dígitos hardcoded, é bug.
- Estado global em variável de módulo (`_cache = {}` sem chave de guild) vaza dados entre clientes. É incidente de segurança, não bug de estilo.
- Um comando lento não afeta só quem clicou — consome o event loop compartilhado. Latência é problema de todos os clientes ao mesmo tempo.
- Toda operação sensível gera `AuditLog`. É o que te protege num chargeback ou numa disputa com cliente.

## Arquitetura do Yuno

Três serviços, orquestrados por `docker-compose.yml`, atrás de Caddy.

```
backend/   FastAPI + SQLAlchemy async + Postgres (SQLite em dev)
           app/api/*.py     → rotas (auth, config, licenses, systems, farm_tickets, webhooks, internal, products, health)
           app/services.py  → regras de negócio + check_permission + audit
           app/models.py    → License, GuildConfig, SystemRecord, AuditLog, PaymentEvent, Farm*
bot/       discord.py 2.4 — cliente puro da API, sem banco próprio
           yuno_bot/main.py         → YunoBot, registro de cogs e views persistentes
           yuno_bot/api_client.py   → YunoAPI (httpx)
           yuno_bot/guards.py       → ensure_allowed / deny
           yuno_bot/server_setup.py → criação de categorias/canais no primeiro setup
           yuno_bot/commands/<mod>/ → cog.py, embeds.py, modals.py, views.py
dashboard/ React/Vite — ativação de licença e configuração web
```

O contrato central é `GuildConfig`, uma linha por servidor com quatro campos JSON:

- `modules` — `{"set": true, "meta": false, ...}`. Liga/desliga módulo por servidor. **É a base do modelo de planos.**
- `command_permissions` — `{"set.solicitar": {"role_ids": [], "channel_ids": [], "category_ids": []}}`. Regra vazia = liberado; lista preenchida = restrição.
- `settings` — configuração livre por módulo, incluindo `discord_setup.channel_ids` e `discord_setup.log_channel_ids`.
- `messages` — textos customizáveis pelo cliente. **Existe no modelo e ainda não é consumido pelo bot.**

`settings.discord_setup` guarda `category_ids`, `channel_ids` e `log_channel_ids`. **É a identidade da estrutura no servidor do cliente** — `server_setup` reconcilia por esses IDs, nunca por nome de canal.

`check_permission` (em `backend/app/services.py`) já valida módulo desligado antes de checar cargo/canal/categoria. O bot só precisa chamá-la corretamente.

## Como se escreve um módulo no Yuno

Todo módulo mora em `bot/yuno_bot/commands/<modulo>/` e se declara ao registry pelo `__init__.py`. **`main.py` e `server_setup.py` nunca são editados para adicionar um módulo** — as listas de cogs, views, canais e chaves de módulo são derivadas do registry (`yuno_bot/modules.py`).

```python
# commands/<modulo>/__init__.py
MODULE = ModuleSpec(
    key="modulo",                      # tem que bater com o nome da pasta
    nome="Sistema de X",
    descricao="...",
    icon="🎯",
    ordem=90,                          # posição canônica nas listas derivadas
    plano_minimo="basico",             # basico | pro | premium
    cogs=(lambda ctx: MeuCog(ctx.bot),),
    views=(lambda ctx: MeuPanelView(ctx.api),),
    setup_channels=(SetupChannel("chave", "nome-do-canal", "operacao", ("modulo.acao",)),),
    log_channel="logs-modulo",
    dashboard_fields=(DashboardField("panel_channel_id", "Canal do painel", "channel"),),
)
```

`cogs` e `views` recebem **fábricas**, não classes, porque as dependências variam: a maioria dos cogs só precisa do bot, `parceria` precisa também do repositório, e as views de `farm_tickets` dependem da instância do próprio cog (`ctx.cog(FarmTicketsCog)`). O loader instancia todos os cogs antes de qualquer view, então essa dependência é sempre resolvível.

Os quatro arquivos de implementação têm responsabilidade única. A separação não é cerimônia: `views.py` precisa ser importável sem arrastar o cog junto, senão as views persistentes quebram no restart.

| Arquivo | Responsabilidade | Regra |
|---|---|---|
| `cog.py` | slash commands, `app_commands.Group`, orquestração | Nunca monta embed nem faz SQL |
| `embeds.py` | funções puras que retornam `discord.Embed` | Sem I/O, sem `await` — isso as torna testáveis sem mock do Discord |
| `modals.py` | `discord.ui.Modal`, validação de input | Valida e converte; delega a persistência |
| `views.py` | `discord.ui.View` de painel fixo | `timeout=None` + `custom_id` estável em todo botão |

Esqueleto de um comando, com a ordem que importa:

```python
class MeuCog(commands.Cog):
    def __init__(self, bot: YunoBot) -> None:
        self.bot = bot

    grupo = app_commands.Group(name="modulo", description="...")

    @grupo.command(name="acao", description="...")
    async def acao(self, interaction: discord.Interaction) -> None:
        allowed, reason = await ensure_allowed(interaction, self.bot.api, "modulo", "acao")
        if not allowed:
            await deny(interaction, reason)
            return
        await interaction.response.send_modal(MeuModal(self.bot.api))
```

Regras que existem por causa de dor real:

- **Guard primeiro, sempre.** `ensure_allowed` antes de qualquer trabalho. Ele já cobre licença, módulo desligado e permissão.
- **`send_modal` não pode vir depois de `defer`.** Discord dá 3 segundos para a primeira resposta; se o comando abre modal, ele tem que ser a primeira coisa. Se precisa de I/O antes, use `defer(ephemeral=True, thinking=True)` e responda com `followup`.
- **Toda `View` persistente precisa de `custom_id` fixo e ser registrada em `setup_hook` via `add_view`.** Sem isso, os botões do painel morrem no primeiro deploy e o cliente abre ticket.
- **Erro de rede nunca vaza como traceback.** `httpx.HTTPStatusError` 403 significa licença inativa e merece mensagem específica; qualquer outro erro vira "não consegui falar com a API do Yuno". O cliente precisa saber se o problema é dele ou seu.
- **Textos visíveis ao usuário saem de `messages` da guild config**, com fallback para o padrão. Um produto vendido para servidores de RP precisa deixar o cliente mudar o tom.

## Portar uma feature do MDM para o Yuno

O código do MDM **não é copiado**. Ele é a especificação funcional de algo que já provou funcionar; a implementação é reescrita no padrão do Yuno. Copiar traz junto o SQLite local, os IDs hardcoded e o acoplamento ao servidor do dono.

Roteiro, em `references/port-checklist.md` com o detalhamento. Resumo:

1. Ler o cog do MDM só para extrair as **regras de negócio** — estados possíveis, quem pode o quê, o que gera log, o que é automático.
2. Identificar o que é **específico do Morro do Mineiro** e precisa virar configuração: nomes de cargo (`| 01 Dono`, `Gerente de Produção`), itens de farm (folha, ópio, seringa, agulha), IDs de canal, fuso horário, valores em reais.
3. Modelar a persistência no backend. Registro simples cabe em `SystemRecord` (`module` + `payload` JSON). Domínio com queries próprias merece tabela — e nesse caso, migração Alembic.
4. Expor rota em `backend/app/api/`, método correspondente em `api_client.py`, e só então escrever o cog.
5. Registrar o módulo no registry, adicionar ao `MODULES` do backend e ao dashboard de configuração.
6. Teste do `embeds.py` e das funções puras. O cog em si não se testa bem — a lógica testável tem que estar fora dele.

**Já validados e em produção no Yuno: `set`, `meta`, `registro`.** Use esses três como referência de padrão. Se algo novo diverge deles, ou você tem uma razão explícita ou está errado.

## Débitos técnicos conhecidos

Mantida em ordem de impacto na venda. Ao resolver um item, remova-o daqui e registre no CHANGELOG.

1. **Não há dashboard de configuração dentro do Discord.** Hoje o cliente precisa sair do Discord e ir no painel web. O MDM resolveu isso muito bem em `cogs/dashboard.py` com Components V2 (`Section` + `accessory`, paginado). É o maior gap de UX do produto e o item mais rentável da lista. O registry já expõe `dashboard_fields`, `icon`, `nome` e `descricao` — a UI pode ser gerada a partir dele.
2. **Nenhum comando verifica `modules`.** `check_permission` valida no backend, mas painéis e botões de view não passam por ele. Módulo "desligado" continua clicável. Com o registry no lugar, um decorator `@requires_module` resolve.
3. **`parcerias_repository` grava SQLite local no container do bot.** Viola o multi-tenant e o estado some no redeploy. Migrar para o backend.
4. **`api_client.py` tem 30+ métodos específicos de farm_tickets.** Domínio vazando para a camada de transporte. Deve ser um cliente genérico com os métodos de domínio nos módulos.
5. **`_apply_set_visibility` itera todas as categorias e todos os canais chamando `set_permissions`.** Em servidor com 80 canais isso é rate-limit garantido e trava o setup na frente do cliente. Precisa operar só nos canais afetados.
6. **Sem Alembic.** Produto vendido sem migração versionada não sobrevive à segunda atualização.
7. **`messages` não é consumido.** Cliente não consegue mudar nenhum texto.
8. **Licença só é validada em `/yuno status` e `/yuno configurar`.** Revogação não tem efeito imediato nos demais comandos.

**Resolvido:**

- Registry declarativo de módulos (`yuno_bot/modules.py`). `main.py` e `server_setup.py` não são mais editados a cada módulo; a divergência de `farm_tickets` entre bot e backend está travada por teste.
- Setup idempotente por ID + `/yuno diagnostico` (`server_setup.ensure_setup_channels`, `diagnostics.py`). Canal renomeado ou movido pelo cliente é respeitado — identidade é o ID, e o bot nunca reorganiza o servidor dele.

## Verificação antes de fechar qualquer entrega

- Nenhum ID de 17-20 dígitos hardcoded: `grep -rnP '\b\d{17,20}\b' bot/ backend/app/`
- Nenhum `sqlite3` ou caminho de `.db` no código do bot
- Nenhum estado global sem chave de `guild_id`
- Módulo novo declara `MODULE = ModuleSpec(...)`; `main.py` e `server_setup.py` intocados
- `python -m pytest backend/tests` verde
- Erro de API não vaza traceback; 403 diz "licença inativa"
- Comando responde em menos de 3s ou usa `defer`
- Testado num servidor Discord limpo com `/yuno configurar` do zero

## Como responder neste projeto

O dono é desenvolvedor e quer decisão, não aula. Entregue o diagnóstico e a correção primeiro; a explicação vem depois e curta.

Quando ele propuser escopo novo, teste antes de concordar: qual o custo escondido, que suposição não está provada, qual trade-off foi ignorado. O padrão de erro dele é acelerar e aceitar demais — quando isso aparecer, aponte o erro de alocação e diga o que cortar ou adiar. Se a ideia for boa, diga que é boa e avance; não invente objeção fraca para parecer criterioso.

Português do Brasil sempre. Código e mensagens ao usuário final também.

## Referências

- `references/mapa-yuno.md` — inventário de arquivos do Yuno, responsabilidades e contratos
- `references/mapa-mdm.md` — inventário do Morro do Mineiro e o que vale portar
- `references/port-checklist.md` — roteiro detalhado de port MDM → Yuno
