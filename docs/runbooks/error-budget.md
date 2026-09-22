# Erros sustentados e orçamento de serviço

O procedimento usa [regras de referência](../../monitoring/rules/reference.yml), o [Compose](../../compose.yml) e as [regras demo](../../monitoring/rules/demo.yml). Comandos e prazos descrevem o ambiente local; resultados de recuperação têm recibos próprios.

O alerta de referência compara a fração de erros com a fração permitida pelo SLO, confirmada por janelas longa e curta e tráfego mínimo. O perfil demo usa janelas próprias menores. Uma execução de minutos não mostra disponibilidade em 30 dias.

Execute os comandos na raiz do projeto, após o setup. O projeto Compose é `pf-api-sentinel`.

## Confira primeiro

No Grafana, separe respostas de sucesso, erros 5xx e quota. Um 503 de saturação é falha do serviço; um 429 de quota contratada é separado e permanece visível. Confira qual perfil está ativo e leia a annotation window antes de interpretar o número.

```promql
sum by (route, outcome) (rate(sentinel_http_requests_total{traffic="business"}[5m]))
sum(rate(sentinel_http_requests_total{traffic="business",outcome="server_error"}[5m]))
```

Compare com o probe pelo proxy. O contador interno cobre requisições observadas pela aplicação; conexões recusadas e erros emitidos pelo proxy exigem a medição do cliente/probe.

## Investigue antes de agir

1. Identifique a rota e o instante em que os erros começaram. Abra traces do serviço api-sentinel no mesmo período e correlacione trace_id/request_id nos logs JSON.
2. Redis indisponível: a quota deve retornar 503 e não pode ser substituída silenciosamente por contador local.
3. Rejeições de entrada/admissão e pool em espera: reduza a carga do laboratório, depois siga saturação. Aumentar a quota pode piorar o incidente.
4. Somente a integração ERP falha: siga o runbook ERP e confirme resumos/vendas funcionando.
5. Erros de contrato/dados exigem corrigir a consulta ou a massa de teste; não classifique resultado incorreto como sucesso.

```powershell
docker compose -p pf-api-sentinel logs --tail 150 api proxy
docker compose -p pf-api-sentinel --profile observability ps
```

## Recuperar e confirmar

Restaure somente o componente que o experimento interrompeu; retire a falha injetada ou interrompa o gerador que iniciou. Verifique status/schema/resultado de consulta comercial e técnica. Aguarde ambas as janelas deixarem a condição e o receiver persistir resolved. Um erro isolado ter desaparecido não indica recuperação sustentada.

## Sem dados de monitoramento

Sem tráfego elegível ou sem coleta, a fração de erro não é uma disponibilidade de 100%. Use o runbook de telemetria e registre a lacuna antes de concluir a causa ou o impacto total.
