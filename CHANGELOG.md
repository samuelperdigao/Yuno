# Changelog

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
