# Yuno

Yuno e um bot SaaS para Discord focado em gestao e organizacao de servidores FiveM.

Esta base entrega a primeira fundacao do produto:

- API FastAPI para licencas, configuracoes, webhook Mercado Pago, auditoria e registros dos sistemas.
- Bot Discord com slash commands globais e validacao de licenca/permissao antes da execucao.
- Dashboard React/Vite para ativacao, configuracao de modulos, permissoes e produtos.
- Docker Compose para VPS com PostgreSQL, Redis, API, bot, dashboard e Caddy.

## Estrutura

```text
backend/    API FastAPI, banco e testes
bot/        Bot Discord em discord.py
dashboard/  Painel web React/Vite
infra/      Proxy HTTPS e arquivos de deploy
scripts/    Rotinas operacionais de backup/restauracao
docs/       Decisoes de arquitetura e operacao
```

## Desenvolvimento local

1. Copie `.env.example` para `.env` e preencha os tokens.
2. Suba a stack:

```bash
docker compose up --build
```

3. Acesse:

- API: `http://localhost:8000/docs`
- Dashboard: `http://localhost:5173`

## Deploy

Deploy simples para o Oracle atual:

```powershell
.\deploy.yuno.cmd
```

O script envia a branch `main` para o GitHub, atualiza `/home/ubuntu/yuno` no Oracle e reinicia `yuno-api` e `yuno-bot`.

## Marca

A logo oficial do Yuno fica em `Yuno.png` na raiz do projeto e tambem em `dashboard/public/Yuno.png` para uso no painel web.

## Comandos principais do bot

- `/yuno status`
- `/yuno configurar`
- `/yuno painel`, `/yuno diagnostico`
- `/set solicitar`, `/set aprovar`, `/set reprovar`, `/set painel`
- `/meta registrar`, `/meta painel`
- `/farm ranking`, `/setup_farm_tickets`, `/setup_farm_meta`, `/setup_farm_painel`
- `/ticket abrir`, `/ticket painel`
- `/parceria cadastrar`, `/setup_parcerias`
- `/encomenda criar`, `/encomenda painel`
- `/setup_ausencia`, `/painel_ausencia`, `/ausencias`
- `/radio alterar`, `/radio painel`
- `/producao registrar`, `/producao painel`
- `/adv aplicar`, `/adv painel`
- `/anuncio publicar`, `/anuncio painel`
- `/hierarquia painel`, `/acao painel`, `/disparo painel`

Os comandos operacionais abrem modais personalizados no Discord. O preenchimento do formulario gera registro no backend, resposta privada para o usuario e log no canal do sistema.

Veja o fluxo completo de publicação e personalização em [docs/paineis.md](docs/paineis.md).

## Operação antes da venda

Depois de ativar a licenca do servidor, use `/yuno configurar` dentro do Discord para o bot criar as categorias/canais padrao, os canais de log por sistema e salvar as permissoes iniciais de cada comando no backend. O usuario precisa ter permissao de gerenciar servidor e o bot precisa ter permissao de gerenciar canais.

Os fluxos do produto e os painéis fixos estão implementados. Antes de liberar uma instalação para cliente, valide no ambiente real:

- Aplicacao Discord OAuth e bot token.
- Credenciais Mercado Pago e validacao final de webhook.
- Dominio, HTTPS e backups na VPS.
- Politica comercial de troca manual de servidor.
- Migrações em uma cópia do PostgreSQL de produção.
- Fluxo `/yuno configurar` → painéis → `/yuno diagnostico` em um servidor Discord limpo.
