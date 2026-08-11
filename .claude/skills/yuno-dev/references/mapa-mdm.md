# Mapa do Morro do Mineiro Bot

O Morro do Mineiro (MDM), em `C:\Projetos\Morro do Mineiro Bot`, é um monólito Discord.py + SQLite criado para uma guild específica. Use-o somente como arquivo histórico de requisitos, casos de borda e comportamento observado.

## Usos permitidos

- Identificar regras que usuários realmente utilizaram.
- Encontrar estados, transições e permissões implícitas.
- Descobrir jobs, listeners, logs e recuperação de falhas.
- Inventariar dados que podem precisar de migração.
- Ler testes como evidência de comportamento antigo.

## Usos proibidos

- Copiar schema, cog, comando, view ou arquitetura.
- Preservar nomes de cargos/canais, IDs, produtos ou prazos fixos.
- Transformar slash antigo diretamente em botão.
- Usar SQLite local, variáveis globais ou arquivos JSON como padrão do Yuno.
- Tratar o dashboard do MDM como contrato da nova Central.

## Arquitetura factual

```text
main.py                    bot e carregamento de cogs
core/                      config, permissões e helpers
services/db_schema.py      schema e migrações SQLite
services/db_service.py     acesso a dados centralizado e muito acoplado
services/log_service.py    resolução e envio de logs
config/paineis.py          definições de painéis
cogs/                      comandos, views, jobs e regras misturados
data/                      banco e configurações locais
```

O MDM não é multi-tenant real, contém IDs e nomes específicos e mistura domínio, persistência e Discord. Isso explica comportamento, mas não serve como fundação.

## Inventário relevante para Farm

| Área | Arquivos típicos | Evidência a extrair |
|---|---|---|
| Metas e entregas | `cogs/farm.py` | ciclo, itens, lançamentos, aprovação e histórico |
| Tickets | `cogs/farm_tickets.py` | propriedade, abertura, controle e encerramento |
| Painel | `cogs/farm_painel.py` | ações oferecidas e feedback aos membros |
| Relatórios | `cogs/farm_relatorio.py`, `ranking_painel.py` | consultas e agregações usadas |
| Advertências | `cogs/farm_advertencias.py` | comportamento antigo, não requisito automático |
| Renderização | `cogs/farm_embeds.py` | informações que usuários precisavam visualizar |
| Persistência | `services/db_schema.py`, `db_service.py` | dados existentes e relacionamentos implícitos |
| Testes | `tests/test_farm_*` | casos de borda comprovados |

Produtos hardcoded, semana fixa, punições automáticas, valores financeiros e cargos por nome são decisões antigas. Não viram requisito novo sem aprovação explícita.

## Outros domínios disponíveis para auditoria futura

Set, ausência, encomenda, rádio, parceria, anúncio, advertência, hierarquia, membros, moderação, ação e disparo possuem implementações antigas. Analise somente quando chegar a vez do módulo, seguindo `legacy-audit.md`.

## Como consultar

1. Ler testes do domínio primeiro.
2. Listar classes/funções antes de abrir arquivos grandes.
3. Buscar regras, queries e transições específicas.
4. Registrar evidência com arquivo e símbolo.
5. Voltar ao novo requisito e decidir preservar, redesenhar, descartar ou migrar.

Nunca concluir “já existe no MDM, então será igual no Yuno”.
