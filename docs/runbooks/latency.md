# Latência acima do objetivo

O alerta combina percentil de sucesso com volume mínimo e persistência. Não compare a latência de 503/429 rápidos com respostas corretas para afirmar melhora. Os histogramas combinam buckets entre réplicas; não calcule média dos p95 individuais.

Execute os comandos na raiz do projeto, após o setup. O projeto Compose é `pf-api-sentinel`.

## Confira primeiro

Abra o dashboard no período do alerta e separe rota, resultado e réplicas. Compare duração HTTP com espera por conexão, tempo Redis, cache miss/contensão e duração ERP. O valor agregado sinaliza onde procurar; ainda não é um diagnóstico causal.

```promql
histogram_quantile(0.95, sum by (le) (rate(sentinel_http_request_duration_seconds_bucket{traffic="business",outcome="success"}[5m])))
histogram_quantile(0.95, sum by (le,pool) (rate(sentinel_db_pool_wait_seconds_bucket[5m])))
sum by (result) (rate(sentinel_cache_requests_total[5m]))
```

## Diferencie espera de trabalho útil

1. SQL lento: no Jaeger, encontre o span PostgreSQL dominante. Compare com EXPLAIN registrado e índices por tenant/loja/data. Não rode uma consulta sem filtro sobre a massa inteira para diagnosticar.
2. Espera de pool: checked_out atinge o limite e aquisição demora/timeouts crescem. Verifique transações/consultas em andamento; aumentar o pool desloca a pressão para PostgreSQL.
3. Cache frio ou expiração: misses e contenção de preenchimento crescem. Confira queries summary e cache_fill; redução de latência sozinha não indica menos consultas.
4. ERP lento: duração externa e deadline/circuito crescem, mas resumo que usa só PostgreSQL deve continuar útil.
5. Event-loop lag e memória crescentes: confira carga recebida e trabalho síncrono/serialização. Não conclua que async permite concorrência ilimitada.

```powershell
docker compose -p pf-api-sentinel logs --tail 120 api
docker compose -p pf-api-sentinel stats --no-stream
```

## Reduzir impacto e confirmar

Interrompa o gerador de carga iniciado pelo teste ou reduza sua taxa. Remova a falha controlada identificada. Preserve timeouts, limites de páginas e política de quota. Confirme consulta correta, espera de pool limitada, retorno do percentil ao objetivo com volume suficiente e resolved na caixa de alertas.

Se os traces amostrados não incluírem o período ou a coleta estiver ausente, registre a lacuna. A falta de span não mostra que um componente é rápido.
