# Coleta e entrega de alertas

Procedimento conferido em **22/09/2026**: [configuração e retenção](../../alert_receiver/config.py), [Compose](../../compose.yml) e [regras demo](../../monitoring/rules/demo.yml). Os comandos e prazos são instruções deste ambiente; não constituem nova medição de recuperação.

Verifique scrape, regras, entrega e gravação dos alertas.

Execute os comandos na raiz do projeto, após o setup. O projeto Compose é `pf-api-sentinel`.

## Confira a cadeia em ordem

1. Prometheus /targets: cada réplica, receiver, Alertmanager e o próprio Prometheus estão presentes e com scrape recente?
2. Prometheus /alerts: a regra está inactive, pending ou firing? Confira a expressão, janela, volume mínimo e perfil ativo.
3. Alertmanager: o alerta chegou, está agrupado ou silenciado? Confira logs de entrega HTTP. A configuração local não aplica inibição, pois o receiver precisa acompanhar a recuperação de cada ocorrência já entregue.
4. Receiver /metrics: confira sentinel_alert_webhooks_total por result, sentinel_probe_config_valid, sentinel_probe_last_run_timestamp_seconds e eventual truncamento. Uma resposta 2xx só ocorre após commit SQLite.
5. Receiver /api/incidents: existe a identidade fingerprint + starts_at e qual é o estado persistido? O histórico distingue repetição, recuperação e firing atrasado.

O alerta de telemetria também verifica `up{job="prometheus"} == 0`: target presente com scrape falhando não equivale a coleta saudável. Três ou mais falhas de webhook em um minuto (demo) ou cinco minutos (referência), persistindo pelo `for` do perfil, sinalizam problema de entrega mesmo quando os targets respondem ao scrape. Confira `alertmanager_notifications_failed_total{integration="webhook"}` por categoria e os resultados de recebimento antes de atribuir a causa. Um erro isolado e uma contagem antiga sem incremento não disparam essa condição.

Este alerta usa a mesma cadeia de entrega sob observação. Enquanto o receiver ou sua credencial estiverem quebrados, ele pode existir no Prometheus/Alertmanager sem chegar à central; não é uma garantia de notificação independente. A produção precisaria de um destino e supervisão externos.

```powershell
docker compose -p pf-api-sentinel --profile observability ps
docker compose -p pf-api-sentinel logs --tail 100 prometheus alertmanager receiver
docker compose -p pf-api-sentinel logs --tail 80 jaeger
```

## Falha do receiver

O receiver usa volume SQLite próprio e não depende de PostgreSQL/Redis da API. Se ele estiver fora do ar, Alertmanager tenta novamente conforme seu comportamento de retry; não há garantia de entrega exatamente uma vez nem de histórico completo durante falhas prolongadas. Erro HTTP 401 exige conferir o mesmo arquivo de segredo nos dois containers sem imprimir seu conteúdo. Erro 413 exige reduzir o grupo de alertas; o limite é real de 64 KiB. Erro 503 de armazenamento não é sucesso e deve ser repetido.

```powershell
docker compose -p pf-api-sentinel --profile observability start receiver
docker compose -p pf-api-sentinel --profile observability logs --tail 80 receiver alertmanager
```

A retenção padrão é 30 dias, configurável por `ALERT_RETENTION_DAYS` entre 1 e 365. Resolvidos ficam visíveis enquanto a última entrega ou reconciliação operacional estiver dentro da janela; ativos não expiram. A lista e os contadores usam o mesmo snapshot SQLite e exibem o corte UTC exato, mesmo que a limpeza física horária ainda não tenha ocorrido. A API distingue total da janela, total do filtro e quantidade exibida (até 100). Eventos usam a mesma janela, limite físico de 10.000 após manutenção e até 100 registros exibidos por ocorrência. O contador deliveries representa entregas acumuladas e pode exceder os eventos retidos; reconciliações são eventos administrativos, não novas entregas. Remover o volume perde o histórico.

## Configuração do probe indisponível

Se sentinel_probe_config_valid está em 0, confira os arquivos de credencial técnica e expected-replicas. O probe não faz uma consulta enquanto esses arquivos são inválidos; sentinel_probe_success e sentinel_expected_replicas ficam NaN, e o timestamp da última consulta real não avança. O alerta correto é de telemetria: o estado do negócio é desconhecido. A central informa “Consulta indisponível”; abra “Detalhes da observação” para conferir o resultado registrado.

Arquivo presente não garante que a credencial ainda esteja autorizada. Uma resposta HTTP 401/403 após consulta válida entra como http_error; confira expiração, revogação e escopo da credencial própria do probe, sem imprimir o token. Ela pode explicar a falha da jornada técnica mesmo quando outros clientes ainda conseguem consultar.

Uma consulta concluída só é considerada recente dentro de `max(15 s, 2 × max(intervalo, deadline))`, publicado em `sentinel_probe_stale_after_seconds`. Horário ausente, sem fuso ou futuro não indica observação atual. As regras de alerta aplicam o maior valor entre esse limite e o piso de 30 s (demo) ou 60 s (referência), além do `for` do perfil. O alerta distingue probe antigo de falha recente da jornada. A central é uma leitura manual: vencê-la na tela não interrompe o probe nem consulta novamente o servidor.

A central não consulta os targets do Prometheus. Réplicas desejadas vêm do arquivo local; réplicas observadas e atualização da coleta devem ser conferidas em `/targets`. Uma consulta técnica aprovada não mostra que ambas as réplicas estejam disponíveis nem que a cadeia de alertas esteja coletando/entregando.

## Backend de traces indisponível

O exportador tem fila limitada e envia de forma assíncrona. A API deve continuar atendendo sem crescimento ilimitado de memória; spans podem ser perdidos durante a falha. Restaure Jaeger e confirme uma requisição nova visível, sem esperar recuperar automaticamente spans descartados.

## Confirmar recuperação

Confirme scrape recente, dados coerentes, probe voltando a atualizar e entrega firing/resolved real. Se o receiver ou Prometheus estiver totalmente parado, ele não pode alertar de forma confiável sobre si mesmo; supervisão externa é necessária em produção. Este laboratório inteiro para junto com o host.

## Ocorrência de perda de réplica sem entrega de recuperação

Compare o estado persistido da central com targets, probe e alertas atuais antes de concluir que a API continua indisponível. A revisão encontrou uma ocorrência de perda de réplica cuja recuperação foi suprimida pela antiga inibição; a configuração foi corrigida, sem apagar o histórico.

Para reconciliar exclusivamente uma ocorrência `SentinelReplicaLost` ainda ativa no ambiente demo, execute `python scripts/reconcile_replica.py ID` na raiz do projeto. O comando recusa targets antigos/ausentes, probe inválido/antigo ou qualquer alerta ainda ativo no Alertmanager. Ele registra `operator_reconciled` e guarda antes/depois em `artifacts/reconciliation-ID.json`. Preserva contagem e horário das entregas originais: não fabrica um webhook resolved nem afirma o instante exato em que o serviço se recuperou. Uma ocorrência já reconciliada não deve ser reconciliada novamente.
