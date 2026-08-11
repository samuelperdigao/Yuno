# Arquitetura funcional do upgrade

## Visão

O Yuno é uma plataforma configurável de gestão e automação para organizações de FiveM, administrada diretamente no Discord.

```text
administrador define
→ Central de Gestão
→ configurações e regras publicadas
→ módulos interpretam
→ Yuno automatiza
→ membros utilizam painéis operacionais
```

A Central é o Control Plane. Os módulos, jobs, listeners e painéis operacionais formam o Runtime.

## Regra de personalização

O Yuno controla:

- estrutura funcional e campos semânticos;
- invariantes, estados e transições;
- segurança, integridade e validação;
- publicadores e automações;
- compatibilidade do Runtime.

O cliente controla, dentro do contrato:

- identidade, textos e aparência permitidos;
- canais, categorias e cargos;
- produtos, tipos, quantidades, prazos e ciclos;
- etapas e comportamentos explicitamente parametrizáveis.

Não oferecer editor livre capaz de remover informação essencial, criar estados inválidos ou ignorar permissões.

## O servidor do cliente

O Yuno se adapta ao servidor; o servidor não precisa se adaptar ao Yuno.

- Não exigir nomes fixos de canais, categorias ou cargos.
- Permitir selecionar estrutura existente.
- Oferecer criação de nova estrutura como opção assistida.
- Persistir identidade por IDs e respeitar rename, move e overwrites do cliente.
- Reconciliar apenas o que pertence ao Yuno e somente quando solicitado ou necessário.

## Separação de interfaces

### Central de Gestão

Uso administrativo: configuração, permissões, diagnóstico, rascunho, prévia, publicação, auditoria e recuperação de painéis.

### Painéis operacionais

Uso dos membros: consultas, tickets, lançamentos, acompanhamento e ações simples autorizadas.

UI não contém regra de negócio. Views transformam interação em chamadas de aplicação e renderizam o resultado.

## Infraestrutura preservável

FastAPI, Pydantic, SQLAlchemy assíncrono, Alembic, PostgreSQL, Redis, cliente HTTP interno, autenticação bot→API, auditoria, logging, registry, views persistentes, publicadores genéricos, Docker, backup e deploy podem permanecer quando o módulo provar que servem ao domínio novo.

Preservar componente não significa preservar seu contrato. APIs internas e abstrações podem ser substituídas de forma incremental.

## O que será redesenhado

Para cada módulo, definir do zero: domínio, entidades, estados, regras, configuração, permissões, Central, painéis operacionais, persistência, serviços, automações, auditoria, concorrência, recuperação, testes e migração.

O código atual contém acoplamentos transitórios que não são arquitetura-alvo:

- `dashboard_fields` deriva status/configuração de estruturas antigas;
- `seed_from_legacy` inicia estado novo a partir de schemas velhos;
- `project_to_legacy` projeta publicação nova de volta para contratos antigos;
- comandos e publicadores especializados continuam existindo no código;
- módulos não migrados dependem de painéis previamente publicados ou aparecem como pendentes.

Esses elementos devem ser avaliados como dívida de transição, não replicados.

## Compatibilidade e migração

1. Fechar o novo domínio sem usar o schema antigo como restrição.
2. Inventariar dados existentes e classificar o que precisa ser preservado.
3. Definir mapeamento explícito e verificável para o modelo novo.
4. Criar adaptador temporário apenas se necessário para rollout seguro.
5. Tornar a nova escrita a fonte de verdade no corte do módulo.
6. Observar, reconciliar e remover o adaptador segundo critério documentado.

Nunca apagar dados antigos antes de backup, validação da migração e autorização específica. Não usar downgrade destrutivo como rollback padrão.

## Estratégia de entrega

- Migrar um módulo por vez em fatias verticais completas.
- Começar pelo Farm para validar domínio relacional, configuração rica, painel operacional, jobs e migração.
- Manter a infraestrutura compartilhada estável enquanto cada fatia é validada.
- Não remover lógica operacional antiga antes do aceite funcional da substituição.
- Usar feature flag ou roteamento por módulo quando a convivência temporária for necessária.

Uma fatia está completa somente quando configuração, publicação, Runtime, auditoria, testes, observabilidade e rollback funcionam juntos.
