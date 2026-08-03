# Configuração dos painéis do Yuno

## Fluxo recomendado para um servidor novo

1. Ative a licença do servidor.
2. Rode `/yuno configurar` para criar ou reconciliar categorias e canais.
3. Rode `/yuno painel` para publicar o painel administrativo geral em `#yuno-painel`.
4. Abra cada módulo no painel geral, confira o estado e use o comando indicado para configurar/publicar seu painel fixo.
5. Rode `/yuno diagnostico` e corrija os itens restantes.

Republicar um painel atualiza a mensagem existente. Se o canal for alterado, o Yuno publica no canal novo, salva a nova referência e tenta remover somente a mensagem antiga criada pelo próprio bot.

## Painéis operacionais

| Módulo | Comando de configuração/publicação |
|---|---|
| Set | `/set painel` |
| Metas | `/meta painel` |
| Farm | `/setup_farm_tickets`, `/setup_farm_meta`, `/setup_farm_painel` |
| Tickets | `/ticket painel` |
| Parcerias | `/setup_parcerias` |
| Encomendas | `/encomenda painel` |
| Ausências | `/setup_ausencia`, `/painel_ausencia` |
| Rádio | `/radio painel` |
| Produção | `/producao painel` |
| Advertências | `/adv painel` |
| Anúncios | `/anuncio painel` |
| Hierarquia | `/hierarquia painel` |
| Ações | `/acao painel` |
| Disparo | `/disparo painel` |

`membros` funciona por eventos de entrada/saída e `mod` contém ações administrativas; por isso não precisam de painel operacional fixo. Ambos continuam visíveis e configuráveis no painel geral.

## Personalização visual

No dashboard web, abra **Personalização dos painéis**, selecione o módulo e configure:

- título;
- descrição;
- cor hexadecimal, por exemplo `#FFC72C`.

Campos vazios preservam o texto e a identidade visual padrão do Yuno. Depois de salvar, republique o painel do módulo para editar a mensagem fixa já existente.

## Ranking do farm

`/farm ranking` e o botão **Ranking Semanal** exibem os dez membros com maior quantidade entregue na semana ISO atual. Entradas em revisão não são contabilizadas; múltiplos tickets do mesmo membro são agregados em uma única posição.
