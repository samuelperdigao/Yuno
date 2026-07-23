# Arquitetura do Yuno

## Modelo de produto

O Yuno roda como um unico bot SaaS, atendendo varios servidores Discord. Cada servidor possui uma licenca lifetime vinculada ao `guild_id`, configuracoes isoladas e trilha de auditoria propria.

## Fluxo de compra

1. Cliente compra via Mercado Pago/Pix.
2. Mercado Pago chama o webhook da API.
3. API registra o pagamento e gera uma licenca lifetime.
4. Cliente entra no dashboard com Discord OAuth.
5. Cliente ativa a licenca em um servidor onde possui permissao administrativa.
6. Bot passa a permitir comandos naquele servidor.

## Limites da primeira versao

- Nao acessa banco de dados do FiveM.
- Nao depende de TXAdmin.
- Toda gestao inicial acontece no Discord e dashboard.
- Troca de servidor da licenca e manual pelo administrador do Yuno.

## Seguranca

- Bot usa token interno para chamadas API.
- Dashboard usa sessao assinada.
- Webhook de pagamento valida segredo compartilhado quando configurado.
- Todas as execucoes sensiveis geram audit log.
- Permissoes podem ser restringidas por cargo, canal e categoria.
