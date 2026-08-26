# Changelog

## 2026-08-26

### Adicionado

- Kit de design compartilhado (`platform/ui_kit.py`): tokens de cor, estados semânticos com emoji e cor, barra de progresso, linha de objetivo, tipografia com rótulo e emoji, onboarding numerado, rodapé `-#` e formatação pt-BR de número, dinheiro, quantidade e data. Guia de estilo em `docs/ui-kit.md`.
- Central de Gestão em lista vertical: um módulo por linha, com selo de estado, explicação e o próximo passo como botão, além do placar de quantos módulos estão no ar e quantos aguardam o administrador.
- Painel do ticket com barra de progresso, avatar do membro, campos rotulados, saúde por objetivo e cor do container acompanhando o estado do ticket.
- Editor de Metas com indicador de progresso dos sete passos e seções numeradas no mesmo padrão do Registro.

### Corrigido

- Português sem acento em toda a superfície visível do bot (Central, Registro, Metas, Tags, Tickets de Farm, diagnóstico, mensagens de erro do roteador e textos padrão do Registro).
- O aviso de ciclo da Meta passa a mudar de cor ao encerrar, em vez de permanecer amarelo.
- Status de sincronização das Tags deixa de exibir o valor cru em inglês vindo da API.
- O verde, o laranja e o vermelho do diagnóstico passam a ser os mesmos do restante do produto.

### Nota de atualização

A Central publicada é reescrita com o layout novo no primeiro boot, pela reconciliação de startup. Onde a mensagem da Central foi apagada ou substituída por outro autor, é preciso rodar `/yuno configurar` novamente.

## 2026-08-20

### Adicionado

- Sistema de Tags domain-first, multi-guild, com vínculos Cargo → Tag versionados e resolução pela hierarquia ao vivo do Discord.
- Sincronização durável individual e em massa, com revisões, leases, retry, cancelamento, diagnóstico e limpeza explícita.
- Navegação compartilhada entre Registro e Tags na Central, preservando rascunhos e publicações independentes.
- Validação contínua em Python 3.10 e PostgreSQL para concorrência, índices parciais e isolamento de jobs.

### Corrigido

- A Central publicada passa a incorporar módulos recém-liberados no reinício sem criar uma mensagem duplicada.
- Uma nova publicação de Tags substitui com segurança qualquer reconciliação global antiga e agenda todos os membros novamente.
- O Registro agenda Tags somente após persistir a identidade durável, sem desfazer aprovações quando a reconciliação falha.

## 2026-08-03

### Adicionado

- Emissão e listagem administrativa de licenças, com referência de venda e dados opcionais do comprador.
- Área de emissão/cópia de chaves no dashboard e script PowerShell para emitir diretamente na produção via SSH.
- Manual comercial completo de ativação, configuração dos comandos, validação e entrega da chave.

### Corrigido

- Webhook Mercado Pago agora falha fechado quando o segredo não está configurado e compara o segredo de forma segura.
- Cadastro por `/parceria cadastrar` e pelo painel passa a usar o mesmo repositório de parcerias ativas.
- Permissões de parcerias deixam de depender do nome do cargo; `/setup_parcerias` exige cargos gerentes configurados por ID.

## 2026-08-02

### Adicionado

- Ranking semanal do farm por servidor em `/farm ranking` e no painel fixo de farm.
- Painéis fixos persistentes para tickets, encomendas, produção e advertências.
- Personalização de título, descrição e cor dos painéis pelo dashboard web.
- Ativação e desativação de módulos dentro do painel geral do Discord.
- Paginação do painel geral para os 16 módulos, respeitando os limites de Components V2.

### Corrigido

- Publicação idempotente: republicar atualiza a mensagem conhecida e evita painéis duplicados.
- Canal e mensagem dos painéis passam a ser persistidos por servidor.
- Botões dos painéis simples sincronizam restrições de canal e cargo com `command_permissions`.
- `/radio alterar` agora valida licença, módulo, canal e cargos configuráveis, sem depender do nome "gerente".
- Painel de ausências passa a ser publicado no canal configurado, não no canal em que o comando foi executado.
- Falhas da API no guard de comandos viram mensagens úteis, sem traceback para o cliente.
- Configuração de visibilidade do SET preserva overwrites existentes e evita chamadas redundantes em todos os canais do servidor.
- Deploy Docker cria e valida backup do PostgreSQL antes de atualizar o código.
