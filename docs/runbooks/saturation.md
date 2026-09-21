# Saturação com espera ou rejeição

Entrada e concorrência são locais ao processo. A quota por tenant é global no Redis. O banco recebe a soma dos pools de todas as réplicas.

Execute os comandos na raiz do projeto, após o setup. O projeto Compose é `pf-api-sentinel`.

## Confira primeiro

No dashboard, confronte tráfego oferecido no relatório de carga com admitidos, rejeitados, requests em voo e espera de pool. Verifique dropped_iterations do k6: gerador saturado impede concluir capacidade naquela taxa.

```promql
sum by (stage,result) (rate(sentinel_admission_total[2m]))
sum by (pool,state) (sentinel_db_pool_connections)
sum by (pool) (rate(sentinel_db_pool_timeouts_total[2m]))
```

503 por falta de capacidade é falha do serviço. 429 só representa quota contratada; não altere o código para mascarar saturação. Um semaphore com milhares de requests esperando seria fila sem limite, portanto a implementação rejeita imediatamente quando o limite local é atingido.

## Reduzir carga

1. Interrompa apenas a execução k6 iniciada para este cenário. Preserve logs, relatório e instante da intervenção.
2. Confira se um tenant está monopolizando a admissão e se o tenant técnico ainda valida a fixture. Justiça por processo não equivale a justiça global.
3. Verifique pool e SQL antes de subir réplicas. Orçamento inicial: 2 réplicas × 1 processo × (4 dados + 2 auth) = 12 conexões, mais ferramentas e margem; PostgreSQL está limitado a 40.
4. Se a falha foi transação bloqueada no laboratório, encerre somente a sessão específica aberta pelo teste. Não use terminação global de sessões do banco.

```powershell
docker compose -p pf-api-sentinel --profile observability ps
docker compose -p pf-api-sentinel logs --tail 100 api postgres
```

## Confirmar recuperação

Volte a uma taxa conhecida como segura. Confirme resultados corretos, ausência de fila crescente, queda de timeouts/rejeições e resolved. Refaça apenas o cenário afetado com duração/taxa limitada. Aceitação com latência crescente não é recuperação, e rejeição rápida não é ganho de desempenho.
