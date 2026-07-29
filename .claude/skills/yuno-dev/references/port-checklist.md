# Checklist de port MDM → Yuno

Roteiro para trazer uma feature do Morro do Mineiro para o Yuno. O código do MDM é **especificação**, não fonte de cópia — ele carrega SQLite local, IDs hardcoded e acoplamento ao servidor do dono.

## 1. Extrair a regra de negócio (só leitura)

Abra o cog do MDM e responda por escrito, antes de escrever qualquer código:

- Quais **estados** a entidade tem e quais transições são válidas?
- **Quem pode** cada ação? (No MDM isso está em `core/permissions.py` ou em checagem de cargo por nome.)
- O que dispara **log** e em qual canal?
- O que é **automático** (task agendada, listener de evento) versus acionado por comando?
- Quais dados persistem e por quanto tempo?

Se a feature tem teste em `tests/`, leia o teste primeiro — ele é a especificação mais confiável do repositório.

## 2. Separar o genérico do específico

Faça a lista do que é do Morro do Mineiro e precisa virar configuração por servidor:

| Tipo | Exemplos no MDM | Vira o quê no Yuno |
|---|---|---|
| Itens de domínio | folha, ópio, seringa, agulha | Catálogo em `Product` ou `settings.<mod>.items` |
| Nomes de cargo | `\| 01 Dono`, `Gerente de Produção` | `role_ids` em `settings` ou `command_permissions` |
| IDs de canal | `DASHBOARD_CHANNEL_ID` | `settings.discord_setup.channel_ids` |
| Fuso, moeda, semana | `America/Sao_Paulo`, domingo 23:59 | `settings.<mod>` com default sensato |
| Textos de embed | strings no código | `messages` da guild config, com fallback |

Regra: **se um cliente diferente precisaria de outro valor, é configuração.** Se todo cliente usaria o mesmo, pode ficar no código.

## 3. Modelar a persistência no backend

Decisão binária:

- **Registro simples** (formulário, aprovação, histórico linear, sem query analítica): usa `SystemRecord` com `module="<nome>"` e o resto em `payload` JSON. Não cria tabela, não cria migração. Prefira isso.
- **Domínio com queries próprias** (agregação, ranking, join, índice por campo do payload): cria tabela em `models.py` + schema Pydantic + migração Alembic.

Não crie tabela "por organização". Cada tabela nova é uma migração a mais para manter em N servidores de clientes.

## 4. Expor no backend

1. Schema in/out em `backend/app/schemas.py`
2. Regra de negócio em `services.py` (ou módulo próprio se passar de ~150 linhas)
3. Rota em `backend/app/api/<modulo>.py`, registrada em `main.py`
4. `audit(...)` em toda operação que altera estado
5. Teste em `backend/tests/`

## 5. Cliente HTTP

Método em `bot/yuno_bot/api_client.py`. Enquanto o débito #5 (client genérico) não for resolvido, siga o padrão existente — mas não adicione mais 30 métodos de um domínio só.

## 6. Escrever o módulo do bot

`bot/yuno_bot/commands/<modulo>/`:

- `embeds.py` — funções puras. Escreva primeiro, teste primeiro.
- `modals.py` — validação de input com `parse_positive_int` / `clean_text` de `shared.py`.
- `views.py` — `timeout=None`, `custom_id` no formato `<modulo>:<acao>` e estável para sempre. Mudar um `custom_id` quebra painéis já publicados nos servidores dos clientes.
- `cog.py` — `ensure_allowed` na primeira linha de cada comando.

## 7. Integrar ao produto

Sem estes passos a feature existe mas o cliente não a encontra:

- [ ] Adicionar a chave do módulo em `MODULES` de `backend/app/schemas.py` (o lado do bot vem do registry; `test_module_registry` falha se as listas divergirem)
- [ ] Declarar `setup_channels` e `log_channel` no `ModuleSpec` (não existe mais lista central)
- [ ] Declarar `MODULE = ModuleSpec(...)` no `__init__.py` — o registry cuida de cog, views persistentes, canais de setup e canal de log
- [ ] Expor no dashboard de configuração — web e, principalmente, in-Discord
- [ ] Definir permissões padrão em `command_permissions`
- [ ] Documentar no `README.md` e no CHANGELOG

## 8. Verificação antes de fechar

- [ ] Nenhum ID de 17-20 dígitos hardcoded: `grep -rnP '\b\d{17,20}\b' bot/ backend/app/`
- [ ] Nenhum `sqlite3` / caminho de `.db` no código do bot
- [ ] Nenhum estado global sem chave de `guild_id`
- [ ] Módulo desligado em `modules` realmente bloqueia comando **e** botão de painel
- [ ] Erro de API não vaza traceback para o usuário; 403 diz "licença inativa"
- [ ] Comando responde em menos de 3s ou usa `defer`
- [ ] Painel sobrevive a restart do bot (view registrada com `custom_id` estável)
- [ ] Testado num servidor Discord limpo, com `/yuno configurar` do zero — é o que o cliente vai fazer
- [ ] `/yuno diagnostico` reporta o módulo corretamente (canais e estado)
- [ ] `/yuno configurar` rodado duas vezes seguidas não duplica nada

## Ordem sugerida de port (fase 1, núcleo genérico)

1. **Dashboard in-Discord** — desbloqueia a configuração de tudo que vem depois
2. `adv` — pequeno, exercita o padrão painel + modal + log
3. `anuncio` — cargos anunciantes exercitam `command_permissions`
4. `hierarquia` — manipulação de cargo, exercita permissão do bot
5. `membros` — listeners de join/leave, primeiro módulo sem slash command
6. `acao` — maior, já com o padrão consolidado
7. `mod` — trivial, fecha a fase
8. `disparo` — exige cuidado com rate limit; deixe por último
