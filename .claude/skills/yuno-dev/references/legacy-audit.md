# Auditoria de legado

Use este processo quando Yuno antigo ou MDM puderem conter requisitos, casos de borda, integrações ou dados importantes. O objetivo é produzir evidência para o domínio novo, não portar código.

## 1. Fixar o requisito novo

Antes de ler o legado, escrever:

- problema atual;
- usuários e resultado desejado;
- regras já decididas pelo produto;
- dúvidas que a auditoria precisa responder.

Sem essa moldura, o formato antigo vira arquitetura por inércia.

## 2. Extrair fatos

Consultar testes antes de arquivos grandes. Para cada comportamento encontrado, registrar:

- ator e permissão;
- estado inicial e transição;
- dados lidos/escritos;
- logs, auditoria e mensagens;
- job/listener envolvido;
- falhas e recuperação;
- arquivo, símbolo ou teste que comprova o fato.

Separar comportamento realmente usado de código morto ou específico da guild.

## 3. Inventariar dados

Listar tabelas, colunas, JSON, arquivos, IDs de mensagem e anexos. Para cada item, classificar:

- obrigatório preservar;
- transformar para o modelo novo;
- arquivar somente para consulta;
- descartar após autorização;
- incerto e dependente de decisão do produto.

Registrar volume, chaves, duplicidades, valores inválidos e dependências. Não planejar migração apenas pelo schema nominal.

## 4. Produzir matriz de decisão

| Evidência legada | Valor para o produto | Decisão | Justificativa | Destino novo |
|---|---|---|---|---|
| comportamento/dado | requisito, borda ou nenhum | preservar, redesenhar, descartar ou migrar | motivo | entidade/caso de uso novo |

Reutilização de componente exige provar:

1. compatibilidade com o domínio novo;
2. isolamento por guild;
3. ausência de IDs e nomes fixos;
4. redução real de complexidade;
5. testes suficientes;
6. nenhuma dependência permanente do schema antigo.

## 5. Desenhar migração depois do domínio

- Mapear chave antiga para identidade nova.
- Definir transformações e defaults explícitos.
- Criar backfill repetível e idempotente.
- Validar contagem, integridade e amostras.
- Registrar erros sem abortar silenciosamente.
- Definir fonte de verdade durante convivência.
- Planejar corte, observação, rollback e remoção do adaptador.

Não usar `seed_from_legacy` implícito como migração. Não manter `project_to_legacy` ou dual-write sem data e critério de remoção.

## 6. Saída da auditoria

Entregar:

- resumo factual do legado;
- casos de borda relevantes;
- matriz preservar/redesenhar/descartar/migrar;
- inventário de dados e riscos;
- decisões que ainda precisam do produto;
- impacto no blueprint do módulo;
- estratégia de migração testável.

## Atalhos proibidos

- “O comando vira um botão.”
- “A tabela já existe, então o domínio será igual.”
- “O modal aceita cinco itens, então esse é o limite.”
- “O cargo tem esse nome no MDM, então será padrão.”
- “Guardar tudo em JSON evita migração.”
- “Compatibilidade temporária pode ficar para sempre.”

O legado responde “o que aconteceu antes”; o novo domínio decide “como o produto deve funcionar”.
