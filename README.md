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

## Interface do bot

Com `CONTROL_PLANE_ENABLED=true`, a árvore pública contém somente:

- `/yuno configurar`

Esse comando reconcilia a estrutura e publica a Central de Gestão. Status,
diagnóstico, ativação e configuração são feitos por botões, seletores e modais
dentro da Central. Metas é o módulo piloto com rascunho, prévia e publicação
versionada; os demais módulos aparecem como **Migração para a Central pendente**
e serão migrados progressivamente. Views persistentes e listeners operacionais
continuam carregados sem expor comandos slash adicionais.

`CONTROL_PLANE_ENABLED=false` mantém temporariamente a interface legada para
rollback controlado. A flag não deve ser alterada sem um sync intencional da
árvore. Tokens administrativos e internos nunca devem ser enviados ao cliente.

Veja o fluxo completo de publicação e personalização em [docs/paineis.md](docs/paineis.md).

## Operação antes da venda

Depois de ativar a licença do servidor, use `/yuno configurar` dentro do Discord
para reconciliar categorias/canais, publicar a Central e persistir sua mensagem.
O usuário precisa ser dono, administrador, possuir **Gerenciar Servidor** ou um
cargo listado em `admin_role_ids`; o bot precisa das permissões indicadas pelo
diagnóstico da Central.

Os fluxos do produto e os painéis fixos estão implementados. Antes de liberar uma instalação para cliente, valide no ambiente real:

- Aplicacao Discord OAuth e bot token.
- Credenciais Mercado Pago e validacao final de webhook.
- Dominio, HTTPS e backups na VPS.
- Politica comercial de troca manual de servidor.
- Migrações em uma cópia do PostgreSQL de produção.
- Fluxo `/yuno configurar` → Central → Metas → rascunho → prévia → publicação em um servidor Discord de teste.
