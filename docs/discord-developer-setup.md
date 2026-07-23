# Discord Developer Setup

Aplicacao configurada no Discord Developer Portal:

- Nome: Yuno
- Application ID / Client ID: `1529883184379072582`
- Redirect URI local: `http://localhost:8000/auth/discord/callback`
- Permissoes do convite: `8` (`Administrator`)
- Scopes do convite: `bot applications.commands`

## Intents ativadas

- Server Members Intent
- Message Content Intent

Presence Intent ficou desligada porque o MVP nao precisa monitorar presenca.

## Segredos

Os valores abaixo foram salvos apenas no `.env` local e nao devem ser enviados para repositorio:

- `DISCORD_BOT_TOKEN`
- `DISCORD_CLIENT_SECRET`

## Link de convite

O link foi salvo no `.env` como `DISCORD_INVITE_URL`.

Quando o bot ja estiver no servidor, abrir esse link novamente e selecionar o mesmo servidor atualiza as permissoes autorizadas pelo Discord.

## Setup inicial no servidor

Para testes, preencha `DISCORD_TEST_GUILD_ID` no `.env` com o ID do servidor. Assim os slash commands sao sincronizados diretamente nesse servidor quando o bot inicia.

Com a licenca ativa, execute `/yuno configurar` em um canal do servidor. O comando cria ou reutiliza esta estrutura:

- `Yuno - Administracao`: `#yuno-logs`, `#set-aprovacao`
- `Yuno - Operacao`: `#set-solicitar`, `#metas-semanais`, `#tickets`, `#parcerias`, `#encomendas`, `#ausencias`, `#radio`, `#producao`
- `Yuno - Logs`: `#logs-set`, `#logs-meta`, `#logs-ticket`, `#logs-parceria`, `#logs-encomenda`, `#logs-ausencia`, `#logs-radio`, `#logs-producao`

O Yuno tambem grava no backend os IDs desses canais em `command_permissions` e `settings.discord_setup.log_channel_ids`. Cada slash command operacional abre um modal personalizado e registra o resultado no log do sistema.
