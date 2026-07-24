# Prompt — Sistema de Encomendas do Yuno

Implemente no bot Yuno o mesmo sistema de encomendas usado no bot original, mas sem qualquer referência a "Morro do Mineiro".

## Objetivo

Criar um sistema de encomendas para Discord com:

- comando `/encomenda`
- comando `/setup_encomenda_painel`
- painel fixo com botão `📦 Registrar Encomenda`
- modal para registrar encomendas
- postagem da encomenda no canal configurado
- log da ação em canal de log, se existir configuração
- respostas ephemeral para confirmação e erros

## Regras importantes

- Não usar nenhuma string, footer, título ou comentário com "Morro do Mineiro".
- Usar "Yuno" apenas se o projeto já seguir esse padrão visual/nome em embeds.
- Se o projeto tiver sistema de dashboard/configuração por módulos, integrar com ele.
- Se não tiver dashboard, criar ou adaptar um setup simples para salvar o canal de encomendas.
- Manter o padrão de arquitetura do projeto atual do Yuno.
- Não remover comandos, cogs ou funções existentes.
- Não quebrar compatibilidade com sistemas já existentes.

## Comportamento esperado

### `/encomenda`

Abre um modal para o usuário registrar uma encomenda.

Antes de abrir o modal, verificar se o sistema de encomendas está configurado.

Se não estiver configurado, responder ephemeral:

```text
❌ O módulo de Encomendas não está configurado.
Configure pelo dashboard ou use /setup_encomenda.
```

### Modal

Título:

```text
📦 Registrar Encomenda
```

Campos:

1. Família
   - label: `Família`
   - placeholder: `Ex: Família Silva`
   - max_length: `100`

2. Quantidade
   - label: `Quantidade`
   - placeholder: `Ex: 50`
   - max_length: `20`

3. Valor
   - label: `Valor (R$)`
   - placeholder: `Ex: 1.500,00`
   - max_length: `30`

4. Data da Encomenda
   - label: `Data da Encomenda`
   - placeholder: `Ex: DD/MM/AAAA`
   - max_length: `10`
   - validar formato brasileiro de data

Se a data for inválida, responder ephemeral com erro.

### Embed da encomenda

Ao enviar o modal, postar no canal configurado um embed com:

- título: `📦 Nova Encomenda Registrada`
- cor: laranja `rgb(230, 126, 34)`
- timestamp atual
- author com nome e ícone do servidor
- campo `👨‍👩‍👧‍👦 Família`
- campo `📊 Quantidade`
- campo `💰 Valor`
- campo `📅 Data`
- footer: `Registrado por {display_name}` com avatar do usuário

Após postar, responder ephemeral:

```text
✅ Encomenda registrada com sucesso em #canal!
```

### Log

Se existir serviço central de logs, enviar um embed de log para o sistema `encomenda`.

Embed de log:

- título: `📦 Encomenda Registrada`
- cor: dourada `#FFD700`
- campos:
  - `👤 Membro`: menção e ID
  - `👨‍👩‍👧‍👦 Família`
  - `📊 Quantidade`
  - `💰 Valor`
  - `📅 Data`
- footer genérico, sem nome de facção:
  - `Yuno — Sistema de Encomenda`
  - ou, se preferir totalmente genérico: `Sistema de Encomenda`

### `/setup_encomenda_painel`

Comando restrito a `manage_guild`.

Esse comando deve postar o painel fixo no canal de interação configurado para o sistema de encomendas.

Embed do painel:

- título: `📦 Painel de Encomendas`
- descrição:

```text
Clique no botão abaixo para registrar uma nova encomenda.

Preencha os dados da família, quantidade, valor e data.
```

- cor: laranja `rgb(230, 126, 34)`
- footer:
  - `Yuno — Sistema de Encomendas`
  - ou `Sistema de Encomendas`

Botão persistente:

- label: `📦 Registrar Encomenda`
- style: `primary`
- custom_id: `encomenda_painel:registrar`
- ação: abrir o modal de encomenda

### Configuração de canal

A função que busca o canal de encomendas deve seguir esta prioridade:

1. Buscar em `system_config` o sistema `encomenda`, usando `canal_interacao_id`.
2. Se não existir, buscar configuração legada, como `canal_encomendas_id`, se o projeto tiver.
3. Se o canal não for encontrado, tentar `fetch_channel`.
4. Se ainda assim falhar, retornar `None`.

Se o canal não estiver configurado, responder ephemeral:

```text
❌ Canal de encomendas não configurado ou não encontrado.
Configure pelo dashboard ou use /setup_encomenda.
```

## Arquivo sugerido

Criar ou adaptar:

```text
cogs/encomenda.py
```

Registrar o cog no carregamento de extensões do bot, por exemplo:

```python
"cogs.encomenda"
```

## Resultado final esperado

Ao terminar, o bot Yuno deve ter o sistema de encomendas funcionando com:

- `/encomenda`
- `/setup_encomenda_painel`
- painel fixo
- botão persistente
- modal
- validação de data
- envio da encomenda no canal configurado
- log opcional
- zero referência a "Morro do Mineiro"
