# Yuno — manual comercial, configuração e validação

Atualizado em **03/08/2026**. Este documento descreve o código, a implantação e o servidor de testes existentes nesta data.

## 1. Veredito direto

O Yuno está apto para **testes internos e venda assistida**, em que você recebe o pagamento, emite a chave e acompanha a primeira configuração do cliente.

Ele ainda não deve ser anunciado como uma compra 100% automática e self-service. Faltam três conclusões comerciais:

1. executar o roteiro manual de aceitação deste documento com contas e cargos diferentes no Discord;
2. hospedar publicamente o dashboard com HTTPS e separar a área administrativa da área do cliente;
3. integrar e validar oficialmente a assinatura e a consulta do pagamento no Mercado Pago, além de entregar a chave por e-mail ou página de obrigado.

O fluxo manual de emissão de chave foi implementado para permitir vendas assistidas sem deixar o webhook aberto.

## 2. O que foi realmente comprovado

| Verificação | Resultado em 03/08/2026 |
|---|---|
| Testes automatizados | **101 passaram** |
| Compilação Python | backend e bot sem erro |
| Build do dashboard | Vite gerou o pacote de produção |
| IDs fixos de Discord no bot/API | nenhum encontrado |
| SQLite dentro do processo do bot | nenhum encontrado |
| API na Oracle | ativa e respondendo `/health` |
| Bot na Oracle | ativo e conectado ao servidor de teste |
| Erros no processo atual do bot | zero desde o reinício de 03:21 UTC |
| Estrutura do servidor de teste | 16 módulos configurados e 14 painéis operacionais publicados |
| Clique completo de todos os botões com vários cargos | **pendente de teste manual** |
| Dashboard público | **não hospedado na Oracle atual** |
| Venda Mercado Pago totalmente automática | **não concluída** |

“101 testes passaram” comprova regras de API, banco, cache, registry, setup idempotente e funções testáveis. Não comprova sozinho que todas as permissões do Discord estão corretas em todos os servidores. O roteiro de aceitação da seção 9 continua obrigatório.

## 3. Modelo do produto

- Um único bot Yuno atende vários servidores.
- Cada compra gera uma chave lifetime de 32 caracteres hexadecimais.
- A chave nasce com status `pending`.
- Na ativação, ela muda para `active` e fica vinculada ao primeiro `guild_id` usado.
- A mesma chave não ativa outro servidor.
- Os estados existentes são `pending`, `active`, `blocked` e `revoked`.
- O cliente recebe somente a chave. **Nunca** recebe `ADMIN_TOKEN`, `BOT_INTERNAL_TOKEN`, token do Discord, chave SSH ou segredo do webhook.

Hoje não existe troca self-service de servidor. Uma troca legítima precisa ser tratada administrativamente e auditada antes de alterar o vínculo.

## 4. Como emitir e passar a chave do produto

### 4.1 Fluxo recomendado para vender agora

1. Confirme o pagamento fora do Yuno.
2. Na máquina do projeto, abra PowerShell em `C:\Projetos\Yuno`.
3. Emita a chave na API de produção:

```powershell
.\scripts\emitir-chave.ps1 `
  -Referencia "PEDIDO-0001" `
  -NomeCliente "Nome do cliente" `
  -EmailCliente "cliente@exemplo.com" `
  -DiscordClienteId "ID_DO_USUARIO_DISCORD"
```

O script usa SSH, lê o token administrativo somente dentro da Oracle e mostra a chave retornada. A referência da venda deve ser única.

4. Copie apenas o valor mostrado em `Chave:`.
5. Envie a chave ao comprador por mensagem privada ou e-mail.
6. Peça o ID do servidor Discord, o nome do servidor e o ID Discord do dono.
7. Ative a chave pela área de ativação do dashboard administrativo ou pela API.
8. Convide o bot e execute a configuração inicial da seção 5.

Quando o dashboard for hospedado, a área administrativa também permite emitir, listar e copiar chaves. Essa área exige `ADMIN_TOKEN` e é exclusiva do vendedor.

### 4.2 Mensagem pronta para o comprador

```text
Sua licença lifetime do Yuno foi emitida.

Chave: COLE_A_CHAVE_AQUI

Esta chave ativa um único servidor Discord e fica vinculada ao primeiro servidor escolhido.
Não publique a chave em canal aberto. Envie para o suporte apenas o ID do servidor e o ID do dono quando solicitado.
```

### 4.3 Ativação pela API

Enquanto não existir uma página pública de cliente, a ativação pode ser feita pelo operador:

```http
POST /licenses/activate
Content-Type: application/json

{
  "license_key": "CHAVE_RECEBIDA",
  "guild_id": "ID_DO_SERVIDOR",
  "guild_name": "Nome do servidor",
  "owner_discord_id": "ID_DO_DONO"
}
```

Uma ativação correta retorna `status: active`. Se a chave já estiver ligada a outro servidor, a API recusa a operação.

### 4.4 Situação do Mercado Pago

O webhook agora **falha fechado** quando `MERCADO_PAGO_WEBHOOK_SECRET` não está configurado. Isso impede que alguém envie manualmente `{"status":"approved"}` e fabrique uma licença.

O webhook atual ainda não é a automação final de venda: falta validar a assinatura oficial do Mercado Pago, consultar o pagamento na API do provedor e entregar a chave ao comprador. Até isso ser implementado e homologado, use a emissão manual depois de confirmar o pagamento.

## 5. Configuração de um servidor novo

### 5.1 Antes de convidar o bot

No Discord Developer Portal, habilite os intents de **Server Members** e **Message Content**. Convide o bot com, no mínimo:

- Gerenciar Canais;
- Gerenciar Cargos;
- Ver Canais;
- Enviar Mensagens;
- Incorporar Links;
- Ler Histórico de Mensagens.

Para todos os recursos, também é recomendável permitir gerenciar mensagens, anexar arquivos, mencionar `@everyone` no canal de metas e ver o registro de auditoria. O cargo do Yuno precisa ficar acima dos cargos que ele atribui ou remove.

### 5.2 Ordem obrigatória

1. Ative a licença para o `guild_id` do cliente.
2. Entre no servidor com uma conta dona, administradora ou com **Gerenciar Servidor**.
3. Execute `/yuno status` e confirme “Licença ativa”.
4. Execute `/yuno configurar`.
5. Execute `/yuno painel`.
6. Configure os painéis especializados, conforme a seção 7.
7. Execute `/yuno diagnostico`.
8. Corrija tudo que não aparecer como configurado.
9. Execute o roteiro manual da seção 9.

`/yuno configurar` é idempotente: pode ser repetido sem duplicar canais. O Yuno identifica a estrutura pelos IDs salvos; se o cliente renomear ou mover um canal, o bot respeita a alteração.

### 5.3 Painel geral

O `/yuno painel` publica o painel administrativo fixo em `#yuno-painel`. Ele mostra os 16 módulos, permite ligar/desligar cada um e informa qual comando especializado conclui a configuração.

Republicar um painel operacional atualiza a mensagem anterior. Se o canal mudar, o Yuno salva a nova mensagem e tenta remover somente a mensagem antiga criada pelo próprio bot.

## 6. Comandos centrais

| Comando | Quem usa | O que faz |
|---|---|---|
| `/yuno status` | qualquer membro | informa se a licença deste servidor está ativa |
| `/yuno configurar` | dono/admin/Gerenciar Servidor | cria ou reconcilia categorias, canais e logs; salva os IDs |
| `/yuno painel` | dono/admin/Gerenciar Servidor | publica ou atualiza o painel geral paginado |
| `/yuno diagnostico` | dono/admin/Gerenciar Servidor | verifica licença, permissões, canais, logs e campos obrigatórios |

## 7. Configuração e funcionamento de cada módulo

### 7.1 SET

Configuração: `/set painel canal_solicitacao:#canal canal_aprovacao:#canal cargo_aprovador:@cargo cargo_aprovado:@cargo`.

- Publica o painel **Pedir Set**.
- Restringe os canais do servidor para o membro novo enxergar a solicitação de SET.
- Libera o canal de aprovação para o cargo aprovador.
- Ao aprovar, pode alterar o apelido e entregar o cargo aprovado.
- `/set solicitar` pede nome e ID FiveM, cria protocolo e envia para aprovação.
- `/set aprovar` pede o protocolo e aplica a aprovação.
- `/set reprovar` pede protocolo e motivo.

Teste mínimo: solicitar com membro comum, aprovar com o cargo correto, confirmar apelido/cargo/log e verificar que um membro sem cargo não aprova.

### 7.2 Metas

Configuração: `/meta painel canal_painel:#canal canal_resultado:#canal cargo_definidor:@cargo`.

- O botão **Definir Meta** abre um construtor privado de até 20 linhas.
- É possível adicionar, editar, remover, limpar e enviar itens.
- Ao enviar, o bot publica a meta no canal de resultado com `@everyone`, cria registro e guarda a última definição para reutilização.
- `/meta registrar` registra produto, quantidade e observação no backend e no log.

O bot precisa de permissão para mencionar `@everyone` no canal de resultado.

### 7.3 Tickets semanais de farm

Configure nesta ordem:

```text
/setup_farm_tickets categorias_tickets:IDS cargos_admin:IDS cargos_participantes:IDS canal_log:#canal canal_painel:#canal categoria_pastas:CATEGORIA
/setup_farm_meta definicao:"Item A: 100, Item B: 50"
/setup_farm_painel
```

`categorias_tickets`, `cargos_admin` e `cargos_participantes` aceitam IDs ou menções.

- **Abrir Ticket Semanal** reserva um ticket aberto por membro/semana e cria o canal privado.
- **Ver Meu Farm** mostra o progresso.
- **Ranking Semanal** ou `/farm ranking` agrega entregas e mostra os dez primeiros.
- **Lançar Farm**, **Ver Comprovantes**, **Assumir Ticket**, **Revisar**, **Aprovar Meta**, **Finalizar Ticket** e **Excluir Ticket** controlam o ciclo.

O backend possui testes de configuração, meta, reserva sem duplicidade, lançamento, ranking, atribuição, fila de logs e finalização.

### 7.4 Tickets gerais

Configuração: `/ticket painel canal:#canal cargo_autorizado:@cargo`. Os dois parâmetros são opcionais; sem canal, usa `#tickets`.

- `/ticket abrir` e **Abrir Ticket** pedem tipo, assunto e descrição.
- O resultado é um registro no backend, uma publicação no canal e um log.
- Este módulo registra a solicitação; não cria um canal privado por ticket.

### 7.5 Parcerias

Configuração: `/setup_parcerias canal_registro:#canal canal_ativas:#canal cargos_gerentes:IDS categoria:CATEGORIA`. A categoria é opcional; os cargos gerentes são obrigatórios.

- O painel possui **Registrar Parceria**, **Editar Parceria** e **Remover Parceria**.
- `/parceria cadastrar` abre o mesmo cadastro oficial do botão; os fluxos foram unificados.
- O cadastro pede família, produto e contatos; depois aguarda até cinco minutos pela imagem do uniforme.
- A parceria ativa recebe uma mensagem própria no canal público; editar atualiza e remover desativa.
- Somente dono/admin/Gerenciar Servidor ou cargos explicitamente configurados podem operar.

Após instalar esta revisão, execute novamente `/setup_parcerias` no servidor de teste.

### 7.6 Encomendas

Configuração: `/encomenda painel canal:#canal cargo_autorizado:@cargo`.

- `/encomenda criar` e **Registrar Encomenda** pedem item, quantidade, prazo, cliente/família e valor/observação.
- Cria registro no backend, publica no canal de encomendas e gera log.

### 7.7 Ausências

Configuração: `/setup_ausencia canal:#canal`, depois `/painel_ausencia`.

- **Registrar Ausência** pede de 1 a 7 dias e o motivo.
- Um novo registro do mesmo usuário atualiza a ausência anterior.
- A mensagem pública é atualizada e o log é gerado.
- `/ausencias` lista ausências ativas.
- Uma tarefa acompanha ausências encerradas e marca avisos processados.

### 7.8 Rádio

Configuração: `/radio painel cargos_autorizados:IDS`.

- Usa o canal `#radio` criado pelo setup e restringe a alteração aos cargos informados.
- `/radio alterar` e **Alterar rádio** pedem o número.
- O bot renomeia o canal para representar a rádio e ajusta as permissões.

### 7.9 Produção

Configuração: `/producao painel canal:#canal cargo_autorizado:@cargo`.

- `/producao registrar` e **Registrar Produção** pedem produto, quantidade e observação.
- Cria registro, publica no canal de produção e gera log.

### 7.10 Advertências

Configuração: `/adv painel canal:#canal cargo_responsavel:@cargo`.

- `/adv aplicar membro:@usuario` abre descrição e dias de advertência.
- O painel permite selecionar um membro e aplicar a advertência.
- Cria registro, publica no canal e gera log.
- Não há expiração automática de cargo; o módulo registra a ocorrência e a duração.

### 7.11 Anúncios

Configuração: `/anuncio painel canal:#canal cargos_anunciantes:IDS`.

- `/anuncio publicar` e **Novo Anúncio** abrem título, conteúdo e opção de arquivo.
- O anúncio é publicado no canal em que o formulário foi aberto e gera registro/log.

### 7.12 Hierarquia

Configuração: `/hierarquia painel canal:#canal cargos_hierarquia:IDS cargos_gerentes:IDS`. Informe a hierarquia do menor para o maior cargo.

- **Gerenciar Hierarquia** seleciona o membro e o novo nível.
- O bot remove os outros cargos da escada e adiciona o escolhido.
- A alteração cria registro e log.
- O cargo do Yuno precisa estar acima de toda a escada.

### 7.13 Membros

Configuração: `/membros configurar cargo_boas_vindas:@cargo`. O cargo é opcional; vazio desliga a atribuição automática.

- Ao entrar, o bot entrega o cargo configurado.
- Ao sair, registra o evento e libera/reconcilia a pasta privada de farm.
- No início do bot, executa reconciliação das pastas.
- Para identificar algumas remoções por moderação, precisa ver o registro de auditoria.

Funciona por eventos e não possui painel operacional.

### 7.14 Ações

Catálogo:

```text
/acao tipo_criar chave:banco_central nome:"Banco Central" emoji:🏦 max_participantes:10
/acao tipo_listar
/acao tipo_remover chave:banco_central
```

Ao criar, um modal adicional pede as regras. `max_participantes` é opcional.

Painel: `/acao painel canal:#canal cargos_gerentes:IDS`.

- `/acao iniciar` ou **Iniciar Ação** permite escolher um tipo cadastrado.
- O fluxo recebe data/horário e cria a mensagem de participantes.
- Membros entram/saem; gerentes adicionam/removem e finalizam.
- Na finalização, informa vitória/derrota, valor quando aplicável e observação.

### 7.15 Moderação

- `/mod limpar quantidade:1..100` apaga mensagens do canal atual.
- `/mod organizar_canais categoria:CATEGORIA todos:true|false` adiciona o separador visual aos canais que ainda não o possuem.

Os comandos passam por licença, módulo e permissão. São destrutivos no Discord e devem ficar limitados à equipe administrativa. Não possuem painel.

### 7.16 Disparo

Configuração: `/disparo painel canal:#canal`.

- **Enviar Mensagem** envia o texto para as pastas privadas em `farm_tickets.folders_category_id`.
- O bot registra as mensagens do lote.
- **Apagar Último Disparo** pede confirmação e remove as mensagens quando possível.
- Restrinja o canal à administração.

## 8. Personalização dos painéis

O dashboard permite definir por módulo título, descrição e cor hexadecimal, por exemplo `#FFC72C`. Campos vazios usam o padrão. Depois de salvar, republique o painel do módulo.

Nem todas as mensagens de sucesso, erro e registros são personalizáveis. A personalização completa ainda é um débito de produto.

## 9. Roteiro obrigatório de aceitação antes da primeira venda

Use um servidor limpo e três contas/cargos: administrador, operador autorizado e membro comum.

1. Ative uma chave nova e confirme `/yuno status`.
2. Execute `/yuno configurar` duas vezes; não pode duplicar nada.
3. Publique `/yuno painel` duas vezes; deve atualizar a mesma mensagem.
4. Configure os 14 painéis operacionais.
5. Reinicie o bot e clique em todos os botões; as views persistentes devem continuar.
6. Em cada módulo, teste um caso válido e um usuário sem permissão.
7. Confirme registro no backend, mensagem pública e log quando aplicável.
8. SET: confirme visibilidade, apelido e cargo.
9. Meta: confirme `@everyone` e reuso da última definição.
10. Farm: abra, lance comprovante, revise, aprove, finalize, veja ranking e tente duplicar.
11. Parceria: cadastre com imagem, edite e remova; membro comum não pode operar.
12. Rádio e hierarquia: confirme edição de canal/cargos.
13. Membros: teste entrada e saída com conta descartável.
14. Moderação: teste somente em canais descartáveis.
15. Disparo: teste duas pastas e apague o último lote.
16. Desative um módulo e confirme bloqueio de comandos e botões.
17. Bloqueie/revogue uma licença de teste e confirme a perda de acesso.
18. Execute `/yuno diagnostico`; não deve apontar pendência.
19. Verifique os logs da Oracle:

```bash
journalctl -u yuno-bot --since "10 minutes ago" --no-pager
journalctl -u yuno-api --since "10 minutes ago" --no-pager
```

Somente depois deste roteiro todos os comandos podem ser classificados como validados de ponta a ponta.

## 10. Servidor de teste atual

- Servidor: `Yuno`
- Guild ID: `1529888894399811775`
- Cargo administrativo: `ADM` (`1529908728118251753`)
- Cargo participante: `1529917922514829412`
- Canal do painel geral: `yuno-painel` (`1533673866872754188`)
- Mensagem do painel geral: `1533673938087968873`
- Painel de farm: `abrir-ticket` (`1532715944466583593`)
- Categoria de tickets de farm: `tickets abertos` (`1530038538416951376`)
- Categoria das pastas de farm: `Yuno - Pastas de Farm` (`1533673890390343841`)

Após o deploy desta revisão, republique `/setup_parcerias` informando `ADM` como gerente e repita `/yuno diagnostico`.

## 11. Pendências comerciais priorizadas

### Bloqueiam venda automática

1. Hospedar dashboard e API atrás de domínio/HTTPS.
2. Criar área pública de ativação com Discord OAuth, sem mostrar/pedir token administrativo.
3. Validar notificações do Mercado Pago e consultar o pagamento antes de emitir.
4. Entregar a chave automaticamente por e-mail/página de obrigado.

### Bloqueiam a afirmação “todos os comandos testados”

1. Completar e registrar o roteiro manual da seção 9.
2. Guardar evidência: data, usuário/cargo, resultado e captura.

### Melhorias depois do piloto

1. Implementar planos básico/pro/premium; hoje todos os módulos são liberados por padrão.
2. Tornar todas as mensagens e registros personalizáveis.
3. Criar troca de servidor com regra comercial e auditoria.
4. Reduzir métodos específicos de farm no cliente HTTP.

## 12. Critério final para começar a vender

- **Venda assistida/piloto:** depois do deploy desta revisão, reconfiguração de parcerias e conclusão do roteiro manual.
- **Venda pública self-service:** depois do dashboard público, OAuth do cliente e integração Mercado Pago homologada.

Não prometa “é só pagar e usar sozinho” enquanto a venda automática estiver pendente. A base operacional é sólida, mas essa diferença separa um bot funcionando de um SaaS vendável com baixo suporte.
