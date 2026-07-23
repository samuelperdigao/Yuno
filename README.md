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

Veja [docs/deployment.md](docs/deployment.md). A Vercel fica responsavel pelo dashboard; API e bot precisam rodar em um host com processo persistente.

## Marca

A logo oficial do Yuno fica em `Yuno.png` na raiz do projeto e tambem em `dashboard/public/Yuno.png` para uso no painel web.

## Comandos principais do bot

- `/yuno status`
- `/yuno configurar`
- `/set solicitar`, `/set aprovar`, `/set reprovar`
- `/meta registrar`
- `/ticket abrir`
- `/parceria cadastrar`
- `/encomenda criar`
- `/ausencia avisar`
- `/radio alterar`
- `/producao registrar`

Os comandos operacionais abrem modais personalizados no Discord. O preenchimento do formulario gera registro no backend, resposta privada para o usuario e log no canal do sistema.

## Status do produto

Depois de ativar a licenca do servidor, use `/yuno configurar` dentro do Discord para o bot criar as categorias/canais padrao, os canais de log por sistema e salvar as permissoes iniciais de cada comando no backend. O usuario precisa ter permissao de gerenciar servidor e o bot precisa ter permissao de gerenciar canais.

Esta e uma implementacao inicial de produto, pronta para evoluir. Os fluxos principais ja existem, mas antes de venda real devem ser configurados:

- Aplicacao Discord OAuth e bot token.
- Credenciais Mercado Pago e validacao final de webhook.
- Dominio, HTTPS e backups na VPS.
- Politica comercial de troca manual de servidor.
