# Perda de réplica e redução de capacidade

O procedimento usa [descoberta e coleta](../../monitoring/prometheus/demo.yml), o [Compose](../../compose.yml) e as [regras demo](../../monitoring/rules/demo.yml). Comandos e prazos descrevem o ambiente local; resultados de recuperação têm recibos próprios.

O Prometheus descobre cada réplica diretamente por DNS do Compose, sem scrape pelo balanceador nem socket Docker. O receiver publica a quantidade desejada lida de expected-replicas. A perda real de uma réplica reduz os processos disponíveis; um target ausente também pode indicar falha de coleta. O probe pode continuar saudável nas duas situações.

Execute os comandos na raiz do projeto, após o setup. O projeto Compose é `pf-api-sentinel`.

## Confira primeiro

Compare a quantidade de targets up do job api com sentinel_expected_replicas. Abra /targets no Prometheus e confira Last scrape, endereço descoberto e erro. Um container ativo sem scrape também pode indicar erro de observação, não processo morto.

```promql
sum(up{job="api"})
sentinel_expected_replicas
```

```powershell
docker compose -p pf-api-sentinel --profile observability ps -a
docker compose -p pf-api-sentinel logs --tail 100 api proxy
```

Não abaixe a quantidade esperada para silenciar uma perda não planejada. Em mudança planejada de escala, scripts/sentinel.ps1 -Action start -Replicas 1 ou 2 atualiza o arquivo antes de aplicar a escala; só então interprete o novo orçamento. Um valor NaN em sentinel_expected_replicas exige verificar sentinel_probe_config_valid e o runbook de telemetria, não concluir que zero réplicas é a quantidade desejada.

## Recuperar a réplica

Se o teste parou um container existente, start api o restaura. Se removeu uma réplica, recrie com a quantidade desejada; o exemplo abaixo é para o perfil de duas réplicas.

```powershell
docker compose -p pf-api-sentinel start api
docker compose -p pf-api-sentinel up -d --no-deps --scale api=2 api
```

Depois da recriação, confirme descoberta do novo endereço no Prometheus e passagem pelo proxy. Não aceite um target antigo como sinal de coleta da nova réplica. Preserve a quota global no Redis; duas réplicas não duplicam a quota do tenant.

## Confirmar recuperação

Verifique dois targets up quando desejadas duas réplicas, probe com resultado conhecido correto e resolved na mesma ocorrência. Execute uma consulta comercial e acompanhe pool/erros. Se o proxy permaneceu com upstream obsoleto, recarregue sua configuração através do Compose do projeto e repita a jornada.

Se a ocorrência foi encerrada pelo operador, a central informa esse estado separadamente. O encerramento não substitui uma entrega de recuperação nem estabelece o instante em que o serviço voltou. Consulte o procedimento de reconciliação no runbook de telemetria.

## Limites

As duas réplicas rodam no mesmo host.
