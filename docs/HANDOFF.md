# Handoff — continuar o Yuno no Claude Code

Documento de retomada. Cole isto (ou peça para ler `docs/HANDOFF.md`) ao abrir o Claude Code no repositório `Yuno`.

Data: 2026-08-02 · Branch `main` · Último commit: `0656ff5`

---

## 0. Estado do repositório

**Tudo commitado, working tree limpo.** 14 commits nesta sessão, do fim da Frente A/B até o fechamento da Fase 2 do plano de fundação. `python -m pytest backend/tests -q` → **94 testes passando**.

**Atenção ao caminho do repositório.** Durante a sessão o working directory apareceu como `C:\Users\sperd\OneDrive\Projetos\Yuno` (funcionou o tempo todo) e depois, sem aviso, o ambiente passou a resolver o mesmo repositório em `C:\Projetos\Yuno`. É o **mesmo repositório** (mesmo histórico git, mesmo HEAD) — não é uma cópia divergente — mas se uma sessão futura reclamar de "diretório não encontrado" num desses dois caminhos, tente o outro antes de assumir que o trabalho sumiu. O MDM teve o mesmo problema: `C:\Users\sperd\OneDrive\Projetos\Morro do Mineiro Bot` vs `C:\Projetos\Morro do Mineiro Bot` (esse último é o que está documentado em `mapa-mdm.md` agora, corrigido nesta sessão).

---

## 1. Contexto do produto

Yuno é um **produto vendido**, não um bot pessoal. Critério de toda decisão técnica: *o cliente consegue configurar isso sozinho, em menos de 10 minutos, sem abrir ticket?*

O outro repositório, **Morro do Mineiro Bot** (MDM), é o bot pessoal do dono — monólito maduro, testado em produção real, banco de features validadas. O código de lá é **especificação, nunca cópia**: carrega SQLite local, IDs hardcoded e regras específicas da facção que precisam virar configuração genérica ao portar. Fluxo sempre MDM → Yuno, nunca o contrário.

Decisão vigente: **SaaS na v1, arquitetura preparada para self-host** (não implementado, só preservado por design — ver `bot/yuno_bot/interfaces.py`).

Detalhe completo, com o estado de cada etapa, em `docs/plano-fundacao.md`. A skill `yuno-dev` (`.claude/skills/yuno-dev/`) carrega o mapa da arquitetura automaticamente — leia antes de reler código.

---

## 2. O que foi feito nesta sessão

Ordem cronológica real. Cada item é um commit.

### Fase 0 — Fundação (bloqueante, agora completa)

- **0.4 — Guard de módulo em views** (`4b05649`): decorator `@requires_module` em `guards.py`. Aplicado nos 9 botões que não passavam por checagem nenhuma (`AusenciaPanelView`, `RadioPainelView`, `FarmPanelView`, `FarmTicketControlView`); `set`/`meta` migrados do `ensure_allowed` inline pro decorator, por consistência.
- **0.5 — Alembic** (`5a76ec3`): `_ensure_compat_columns` (ALTER TABLE manual) virou migração versionada de verdade. Duas migrações: baseline (schema como está em produção hoje) + colunas de pasta de membro. `create_database()` adota banco criado antes do Alembic existir via `stamp` — é o caminho que a **produção real ainda não percorreu**, só testado contra simulação.
- **0.6 — Abstração de storage/licença + migração de parcerias** (`2214c6a`): `GuildConfigRepository`/`LicenseProvider` como protocolos estruturais (`interfaces.py`). `parcerias_repository` saiu do SQLite local (perdia estado a cada redeploy) para o backend (`app/parceria.py`, tabelas `parcerias`/`parceria_configs`).

### Fase 1 — Dashboard dentro do Discord

- **`bae8a5e`**: `/yuno painel` — board de status dos módulos (Components V2 cru, payload manual porque a versão de discord.py do projeto não tem `LayoutView` nativo). **Não é um editor de configuração** — cada módulo já tinha comando próprio com seletor nativo (`/set painel`, `/meta painel`); o painel mostra estado (configurado/incompleto/desligado) e aponta o comando certo. Essa foi uma correção de escopo feita em conjunto com você no meio da sessão — a ideia original (modal genérico por campo, copiando o padrão do MDM) teria arriscado duplicar/perder efeitos colaterais de comandos já testados.
- Auditoria de `dashboard_fields`: 6 dos 9 módulos existentes tinham metadata errada ou descrevendo campo inexistente desde a criação do registry (0.1). Corrigido módulo a módulo.

### Fase 2 — Port do núcleo genérico do MDM (7/7 módulos)

Todos seguem o mesmo padrão: `helpers.py` puro (testável sem Discord) + `embeds.py` + `modals.py`/`views.py` + `cog.py` + `__init__.py` com `MODULE = ModuleSpec(...)`.

1. **`adv`** (`92c7de7`) — advertências manuais. `SystemRecord`, sem tabela nova.
2. **`anuncio`** (`3c807f0`) — anúncios com `@everyone`. Primeiro módulo com `command_permissions` configurado via comando dedicado (`/anuncio painel <canal> <cargos>`).
3. **`hierarquia`** (`4508290`) — promoção/rebaixamento numa escada de cargos. Generalização real: MDM comparava por **nome** de cargo contra lista fixa de 11 nomes do próprio servidor; Yuno compara por **ID**, configurável (`settings.hierarquia.role_ids`).
4. **`membros`** (`3913e2a`) — listeners de entrada/saída. `release_member_folder` novo em `farm_tickets/helpers.py`: libera a pasta do farm quando o membro sai (renomeia pra conter "livre", remove overwrite).
5. **`acao`** (`6a5c9e0`) — o maior e mais arriscado. Achados: `cogs/acao.py` do MDM tinha ~500 linhas de código morto (implementação antiga sombreada, nunca registrada); o catálogo de missões (`ACOES`, 16 entradas específicas do MDM) virou `settings.acao.tipos`, configurável via `/acao tipo_criar` — **decisão tomada com você antes de implementar**. `GET /systems/{module}/records/{record_id}` novo no backend (faltava um jeito do bot buscar 1 registro por ID).
6. **`mod`** (`8f7333b`) — `/mod limpar`, `/mod organizar_canais`. Único módulo sem nada específico da facção pra separar.
7. **`disparo`** (`327b962`) — disparo de mensagem em massa pras pastas de farm. Achado: a categoria hardcoded e a regex de reconhecimento de pasta do MDM eram um sistema-irmão nunca conectado ao `farm_tickets` — viraram `settings.farm_tickets.folders_category_id` + reaproveitamento direto de `parse_member_folder`. Histórico local em JSON virou `SystemRecord`.

Registry final: **16 módulos** (`set, meta, ticket, farm_tickets, parceria, encomenda, ausencia, radio, producao, adv, anuncio, hierarquia, membros, acao, mod, disparo`).

---

## 3. Onde parou: Fase 3 (farm genérico) — decisão tomada, nada implementado ainda

O plano original descrevia a Fase 3 como "portar ranking, relatório e advertência automática do farm do MDM". Ao ler o código-fonte de verdade (`farm.py` 1707 + `farm_painel.py` 603 + `farm_relatorio.py` 505 + `farm_advertencias.py` 1164 = 4201 linhas), ficou claro que **isso não é uma extensão do `farm_tickets` que já existe** — é um sistema paralelo com modelo fundamentalmente diferente:

- **Quota obrigatória, não opt-in.** Todo membro com cargo "permitido" é obrigado a entregar a meta semanal; `farm_relatorio.py` reporta quem *deveria* ter entregado e não entregou. `farm_tickets` é opt-in (reserva se quiser).
- **Três tipos de valor** (dinheiro/colete/itens), cada um com modal e parsing próprios.
- **`farm_advertencias.py` é um motor de punição completo**, não um aviso automático simples: 3 tiers escalonados com multas reais em reais fictícios (R$300.000 → R$500.000 → PD), cargos de advertência auto-atribuídos por tier, isenção por rank de hierarquia (`"| 02"` pra cima), isenção por ausência registrada, fluxo de fechamento semanal com claim/finalize.

**Decisão tomada com você:** portar só o **ranking**, em cima do `farm_tickets` que já existe e já está testado — sem quota obrigatória, sem motor de punição. Isso ficou **registrado como decisão pendente**, não como "não vamos fazer nunca": se quiser o relatório de pendentes ou o motor de advertência automática depois, são features novas de verdade (não um port), cada uma com suas próprias perguntas de design (quantos tiers? multa configurável? isenção por quê?).

**Nada disso foi implementado ainda.** A conversa foi interrompida na decisão de escopo, antes de qualquer código.

### O que fazer a seguir, concretamente

1. **Implementar `/farm ranking`** (ou nome equivalente) agregando `FarmTicketEntry`/`FarmTicket` do backend — quem entregou mais essa semana, dentro do modelo opt-in que já existe. Precisa decidir: rota nova em `backend/app/api/farm_tickets.py` (agregação por SQL) ou o bot busca os tickets da semana e agrega em Python (mais simples, mas N+1 se o servidor tiver muitos tickets — para volume normal de uma facção isso não é problema). Recomendo a rota agregando no backend, mesmo padrão de `progress_from_entries` que já existe em `backend/app/farm_tickets.py`.
2. Depois do ranking: **Fase 4 (acabamento comercial)** — `messages` consumido de fato (cliente edita texto/cor de embed), validação de licença com cache curto em todos os comandos (hoje só 3), onboarding guiado por DM, página de status/changelog, backup automatizado.
3. Decisão em aberto, não urgente: se/quando portar relatório de pendentes e motor de advertência automática do farm — exige definir com o dono um modelo de "quota obrigatória" configurável antes de escrever qualquer código.

---

## 4. O que ainda não foi validado (fica mais crítico a cada sessão)

**Nada do que foi construído nesta sessão — nem no que já existia — rodou contra Discord real ou Postgres real.** Tudo foi provado com teste de unidade e API simulada (SQLite). Isso já estava no handoff anterior e continua verdade, agora para uma superfície bem maior:

1. `docker compose up --build` e conferir que a API sobe com as migrações do Alembic aplicando do zero.
2. **Importante:** o caminho de adoção do Alembic (`stamp` numa produção que nunca teve `alembic_version`) só foi testado contra uma simulação fiel — nunca contra o Postgres real do servidor Oracle. Vale backup do banco antes do próximo deploy que inclua isso.
3. Convidar o bot num servidor Discord limpo, `/yuno configurar`, depois `/yuno painel` — conferir que o board de status renderiza (payload V2 cru é o tipo de coisa que só quebra em produção).
4. Testar pelo menos 2-3 dos 7 módulos novos de ponta a ponta: `/adv aplicar`, `/anuncio painel` + `/anuncio publicar`, `/acao painel` + fluxo completo de uma ação (entrar, finalizar, ver pagamento).
5. `/hierarquia painel` com uma escada de verdade — o fluxo de 3 níveis (botão → seleção de membro → seleção de cargo) é o mais frágil de testar sem Discord real.
6. Testar `membros`: entrar/sair de um servidor de teste e conferir o log + liberação de pasta (`release_member_folder`).

---

## 5. Débitos técnicos conhecidos (lista atual, ver `.claude/skills/yuno-dev/SKILL.md`)

1. **`api_client.py` tem 30+ métodos específicos de farm_tickets.** Domínio vazando pra camada de transporte.
2. **`_apply_set_visibility` itera todas as categorias/canais chamando `set_permissions`.** Rate-limit garantido em servidor com 80+ canais.
3. **`messages` não é consumido.** Cliente não consegue mudar texto nenhum. (Vira item da Fase 4.)
4. **Licença só é validada em `/yuno status` e `/yuno configurar`.** Revogação não tem efeito imediato nos demais comandos. `/radio alterar` nem isso faz — só checa cargo hardcoded, nunca módulo/licença.
5. **Não existe conceito de plano por licença.** `plano_minimo` é declarado em todo `ModuleSpec` mas sem ligação com `License`/`GuildConfig` — bloqueia o CTA de upgrade no painel e qualquer diferenciação de preço por módulo.
6. **`radio`, `encomenda`, `producao`, `ticket` e `adv` não têm como restringir por cargo.** Só o canal criado por `/yuno configurar`. Achado ao auditar o dashboard.
7. **Fase 3 do farm (relatório de pendentes + motor de advertência automática) não tem modelo de dados no Yuno.** Ver seção 3 acima — exige decisão de produto antes de virar código.

---

## 6. Comandos úteis

```bash
# suite completa
cd backend && python -m pytest tests -q

# inspecionar o registry sem subir o bot (16 modulos esperados)
cd bot && python -c "from yuno_bot.modules import discover_modules; \
  [print(f'{s.ordem:>3} {k:<13} {s.plano_minimo:<8}') for k,s in discover_modules().items()]"

# alembic, a partir de backend/
alembic revision --autogenerate -m "descricao"
alembic upgrade head

# higiene multi-tenant (deve vir vazio)
grep -rnP '\b\d{17,20}\b' bot/yuno_bot backend/app --include="*.py"
```

Nota de ambiente: `backend/tests/test_api.py` pode dar `PermissionError` ao rodar dentro de pasta sincronizada por OneDrive (o `unlink` do `.db` esbarra no OneDrive segurando o arquivo). Não é bug de código — rodar em `C:\Projetos\Yuno` (fora do OneDrive) evita o problema, e é o caminho que a sessão atual acabou usando de qualquer forma.

---

## 7. Prompt sugerido para abrir a próxima sessão

> Leia `docs/HANDOFF.md` e `docs/plano-fundacao.md`. A skill `yuno-dev` tem o mapa da arquitetura — use antes de ler código. O repositório está em `C:\Projetos\Yuno` (working tree limpo, 94 testes passando). Fases 0, 1 e 2 do plano de fundação estão completas e commitadas (16 módulos no registry). Ficou pendente a Fase 3: já decidimos portar só o `/farm ranking` em cima do `farm_tickets` existente (sem quota obrigatória, sem motor de punição — isso é MDM-específico e viraria feature nova, não port). Comece implementando o ranking. Antes de escrever código, me diga se prefere agregar no backend (rota nova em `app/api/farm_tickets.py`) ou no bot (buscar tickets da semana e somar em Python) — e, depois disso, nada nesta sessão rodou contra Discord ou Postgres reais, então vale considerar quando parar pra validar isso antes de empilhar mais módulos.
