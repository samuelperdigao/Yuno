# Central de Gestão e painéis do Yuno

## Modo Control Plane

Com `CONTROL_PLANE_ENABLED=true`, `/yuno configurar` é o único comando slash
público. Ele valida licença e administrador, reconcilia a estrutura por IDs,
publica ou atualiza a Central em `#yuno-painel` e persiste a referência da
mensagem. Rodar o comando novamente não duplica categorias, canais ou Central.

Toda administração ocorre por componentes do Discord:

- **Status** e **Diagnóstico** ficam na Central;
- cada módulo pode ser ativado ou desativado pela sua sessão administrativa;
- módulos ainda não integrados exibem **Migração para a Central pendente**;
- nenhum texto orienta a usar comandos slash antigos.

As sessões administrativas são efêmeras e pertencem ao usuário que as abriu.
Podem administrar a Central o dono da guild, administradores, membros com
**Gerenciar Servidor** ou cargos presentes em `admin_role_ids`.

## Metas: módulo piloto

Ao abrir **Metas**, a Central oferece:

- **Configurar**: seleciona canal do painel, canal de resultado e cargo com
  seletores nativos; edita itens pelo builder existente e aparência por modal;
- **Prévia**: mostra o embed final, canais, cargo, itens, versão seguinte,
  estado do módulo e diagnósticos, sem criar ou editar mensagem pública;
- **Publicar**: revalida domínio, Discord, revisão e permissão do administrador,
  pede confirmação e atualiza o painel operacional;
- **Ativar/Desativar** e **Diagnóstico**.

Salvar cria uma nova revisão do rascunho. O Runtime continua usando somente a
versão publicada projetada em `GuildConfig`. Duas sessões não podem sobrescrever
o trabalho uma da outra: revisão divergente retorna conflito e exige recarga.

O painel operacional de Metas permanece persistente e funciona sem slash:
**Definir Meta** abre o builder para adicionar, editar, remover e limpar itens,
confirmar a definição, publicar no canal de resultado e registrar a operação.
Quando não há definição operacional recente, os itens padrão publicados são a
sugestão inicial.

## Publicação segura

Na primeira publicação, o Yuno cria o painel. Publicações seguintes atualizam a
mesma mensagem quando canal e referência continuam válidos. Ao mudar de canal,
o painel novo só substitui o antigo depois que a API confirma a publicação.

Se a persistência falhar, uma mensagem nova é apagada ou uma mensagem editada é
reconstruída com a versão publicada anterior. O rascunho é preservado e a versão
publicada não avança. Mensagens anteriores só são editadas ou removidas quando
pertencem ao próprio bot.

## Rollout e rollback

O rollout exige habilitar `CONTROL_PLANE_ENABLED=true`, reiniciar o bot e
sincronizar intencionalmente a árvore reduzida global e do servidor de teste.
Não envie `ADMIN_TOKEN`, `BOT_INTERNAL_TOKEN` ou outros segredos ao cliente.

Rollback excepcional:

1. definir `CONTROL_PLANE_ENABLED=false`;
2. reiniciar o bot;
3. sincronizar a interface legada somente como contingência;
4. manter `module_config_states` no banco, sem downgrade destrutivo;
5. corrigir o problema e reabilitar a Central;
6. sincronizar novamente somente `/yuno configurar`.

## Limitação do MVP

Somente Metas possui `ControlPlaneSpec`. Os outros 15 módulos mantêm views e
listeners existentes quando independentes de slash, mas ainda não oferecem
editor completo na Central. O dashboard React não faz parte deste MVP.
