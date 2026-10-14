# Central de incidentes

Use a central para localizar uma ocorrência, conferir seu período e abrir métricas, traces ou o runbook. A página mostra registros do receiver e uma consulta de referência da API. Abra a URL da sua execução, indicada no [roteiro operacional](demo.md); a [galeria](screenshots.md) apresenta um exemplo com dados sintéticos.

## Ler o resumo

| Gráfico | O que conta | Escopo |
| --- | --- | --- |
| Situação dos incidentes | Em andamento e Finalizados | Totais retidos, independentemente do filtro da fila. Finalizados inclui recuperações e encerramentos administrativos. |
| Inícios por dia | Inícios nos sete dias UTC até a leitura | Apenas os até 100 registros carregados pelo filtro atual; não representa todo o histórico. |

Os dois gráficos da central têm rótulos e tabelas em Ver dados. Mudar o filtro altera a fila e a amostra diária; os totais retidos continuam contando todos os estados. Incidentes ativos não expiram. Finalizados seguem o prazo de retenção indicado na página.

Contagem ausente aparece como sem dado. Datas sem fuso, inválidas ou futuras são excluídas da amostra diária com aviso; sem horário de leitura válido, o período fica indisponível. Zero significa nenhum início válido contado naquele dia e naquela amostra. Os gráficos não medem disponibilidade, volume de entregas ou taxa de falhas da API.

## Localizar uma ocorrência

Selecione Todos, Em andamento ou Finalizados. Confira o ID, título e período antes de abrir Investigar. Identificação e entregas ficam disponíveis por expansão na própria linha. Voltar à central preserva o filtro e aponta para a ocorrência.

A fila carrega até 100 registros por página. Use **Ocorrências seguintes** para percorrer a fila e **Primeira página** para reiniciar; o botão Voltar do navegador recupera a página anterior. O detalhe e seu runbook mantêm o filtro e o cursor no retorno à central. A API `/api/incidents` devolve `next_cursor`; passe esse valor como `cursor` sem alterar o filtro. Cursor inválido retorna 422 com orientação para reiniciar.

Cada página usa uma leitura consistente de lista e totais. A ordem usa estado, última atividade e ID como desempate; novas entregas podem mudar a posição de um incidente entre páginas. Não é um snapshot congelado durante toda a navegação: atualize a leitura para conferir mudanças. A posição exibida conta os registros percorridos e os gráficos diários continuam limitados à página atual.

Para abrir diretamente um registro retido, use o campo ID do incidente. Ele aceita um inteiro positivo até `9223372036854775807`, com até 19 dígitos ASCII. Entrada inválida mostra erro junto ao campo e mantém o filtro. Registro ausente não demonstra ausência de falha naquele período.

### Identidade e atualização de bases existentes

IDs de novas ocorrências usam a sequência persistente do SQLite (`AUTOINCREMENT`), independente da retenção. Apagar o maior ID ou esvaziar o histórico não permite reutilizá-lo. Na inicialização, bases antigas são migradas em transação: IDs retidos e eventos são preservados, índices são recriados e as referências são verificadas antes do commit. Faça backup consistente do SQLite e pare o receiver antes de atualizar; não copie apenas o arquivo principal enquanto houver WAL ativo.

A base antiga não registrava o maior ID já apagado. A migração conhece apenas os IDs ainda presentes: a garantia de não reutilização começa no maior ID preservado durante a atualização. Links de registros apagados **antes** dessa fronteira não são recuperáveis nem têm identidade garantida; não os use como evidência após migrar. Bases novas e exclusões após a migração têm a garantia completa. Não apague nem reduza `sqlite_sequence` durante a operação.

## Distinguir período e entregas

O detalhe mostra o período completo registrado, com seus extremos legíveis em texto:

- Em andamento: início informado pelo alerta até a última entrega recebida.
- Resolvido: início e recuperação informados pelo alerta.
- Encerrado pelo operador: início informado até o encerramento administrativo.

O intervalo entre esses horários não demonstra indisponibilidade contínua nem mede MTTR. Horário ausente, sem fuso ou invertido deixa o período indisponível.

O histórico usa outro relógio: `received_at`, o momento em que o receiver recebeu cada entrega. Mostra até 100 eventos recentes, dos mais novos para os mais antigos. Esses horários podem diferir dos horários informados pelo alerta. Expanda Origem e interpretação para conferir a transição.

Uma repetição preserva a ocorrência. Firing atrasado é registrado sem reabrir um incidente finalizado. Encerramento administrativo não confirma recuperação da API e não acrescenta uma entrega ao contador. A retenção pode deixar menos eventos disponíveis que o total de entregas acumuladas; histórico vazio não significa que nunca houve entregas.

## Conferir a leitura e o probe

Leitura de identifica o instante da página em UTC. Atualizar leitura ou Atualizar ocorrência consulta a página novamente; não há polling. Estado e eventos do detalhe são lidos no mesmo snapshot SQLite.

O probe executa uma consulta autenticada pelo proxy e confere status, schema e valores da [fixture](../data/fixtures/manual-sales.json). Seu instante e validade são próprios, distintos da data da página. Consulta vencida, pendente, desativada ou com erro não confirma saúde. Mesmo um resultado válido cobre aquela consulta e aquele dataset, sem demonstrar disponibilidade global.

Use Ver probe para abrir Escopo da leitura e o diagnóstico da consulta. A fila vazia, um gráfico zerado ou um trace ausente também não substituem essa verificação.

## Abrir evidências e tratar erros

Os links de Grafana e Jaeger usam o período da ocorrência e os serviços da mesma execução. Recortes maiores são limitados às últimas 24 horas, com indicação na página; o detalhe mantém o período completo. Grafana recebe instantes em milissegundos e Jaeger em microssegundos. Datas desconhecidas não geram um intervalo histórico inventado. Regras atuais no Prometheus podem diferir das condições registradas na ocorrência.

Ausência de traces pode decorrer de amostragem, retenção ou coleta indisponível. Confira métricas, logs e coleta antes de atribuir uma causa. Os links de ferramentas preservam o contexto de retorno; ID e filtro são validados e retirados do redirecionamento ao serviço de destino.

Erros temporários podem oferecer Tentar novamente, conservando ID e filtro. Respeite a orientação da página e confira o endereço da execução. A central é de leitura: não executa comandos de runbook nem encerra incidentes por botão. Antes de executar um procedimento, use o projeto e os arquivos Compose da sua execução, conforme o [roteiro](demo.md).
