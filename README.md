# API Sentinel

Construí uma API local pra um problema chato de integração: a loja precisa consultar vendas certas mesmo quando o ERP trava ou fica lento, e um cliente não pode derrubar os outros. Usei FastAPI, PostgreSQL e Redis. Os dados e o ERP são sintéticos.

![Central após recuperação: zero incidentes em andamento e os 21 resolvidos](docs/screenshots/followup-central-desktop.png)

Pus um NGINX na frente de duas réplicas que dividem quota e cache. Prometheus, Grafana, Jaeger e uma central de alertas mostram o que aconteceu em cada teste.

## O que eu quis provar

Rodei local em 21/09/2026 (FastAPI 0.141.1/Starlette 1.3.1) e conferi cada número contra as linhas brutas do banco:

- ERP lento: 114 consultas comerciais corretas e 37 falhas esperadas do ERP, sem drop; na recuperação, 101/101 corretas.
- Quota a 60 chegadas/s por 10 s: 300 respostas corretas e 301 recusas 429, com uma ou duas réplicas. No isolamento, o outro tenant terminou 51/51.
- Cache frio/quente/expirado: 1 / 0 / 1 SQL por fase. Com o Redis parado, recusei a consulta sem gerar SQL de resumo.
- Dois alertas reais subiram e fecharam em 33 s e 20 s. Passaram 229 testes isolados, 70 HTTP e 47 casos de Prometheus.

Os arquivos da execução estão em [verificação](docs/verification.md) e [desempenho](docs/performance.md); resumo e alertas em `artifacts/problem-review/`. O porquê está em [problem-solution.md](docs/problem-solution.md).

## Decisões que tomei

- Quota em janela fixa de 1 s no Redis, dividida entre as réplicas. Simples e previsível; aceito burst na fronteira da janela.
- Admissão e circuito locais a cada processo, pra cada réplica se proteger sem depender do Redis pra decidir.
- Single-flight no cache pra o cache frio não virar stampede no banco, sem furar a quota.
- Cancelo o SQL e limito um ERP que manda bytes devagar, em vez de deixar a conexão pendurada.
- Deixei de fora escala distribuída de verdade: duas réplicas nesta máquina mostram coordenação, não cluster.

## Rodar

Docker Desktop (Linux), PowerShell e Python 3.11+, uns 2 GiB de limite. O primeiro setup baixa imagens; depois não sai pra rede.

```powershell
./scripts/sentinel.ps1 setup -Replicas 2
./scripts/sentinel.ps1 check
./scripts/sentinel.ps1 test
./scripts/sentinel.ps1 demo
```

No Linux, os comandos equivalentes estão no CI ([ci.yml](.github/workflows/ci.yml)).

| Serviço | Local |
|---|---|
| Central de alertas e runbooks | [localhost:9184](http://localhost:9184/) |
| Grafana | [localhost:3104](http://localhost:3104/d/sentinel/api-sentinel) |
| API e Swagger | [localhost:8104/docs](http://localhost:8104/docs) |
| Jaeger | [localhost:16684](http://localhost:16684/) |
| Coleta por réplica | [localhost:9104/targets](http://localhost:9104/targets) |
| Alertmanager | [localhost:9194](http://localhost:9194/) |

Tudo em `127.0.0.1`. Os Bearer tokens saem no setup pra `.runtime/demo.json` (ignorado pelo Git). As credenciais do `.env.example` são só locais.

```powershell
$t = Get-Content .runtime/demo.json -Raw | ConvertFrom-Json
Invoke-RestMethod 'http://127.0.0.1:8104/v1/stores/1/summary?start=2026-01-01&end=2026-01-31' -Headers @{Authorization="Bearer $($t.tenant_a)"}
```

Rotas: lojas autorizadas, resumo por período, vendas por cursor e SKU no ERP. A massa vai de 1º/01 a 1º/03/2026; dinheiro em centavos. [Contrato de dados](docs/data-contract.md).

## Onde está cada coisa

| Pergunta | Código |
|---|---|
| Como impedi filas ilimitadas? | [admission.py](src/api_sentinel/admission.py), [db.py](src/api_sentinel/db.py) |
| Tenant, dinheiro e paginação certos? | [auth.py](src/api_sentinel/auth.py), [queries.py](src/api_sentinel/queries.py), [cursor.py](src/api_sentinel/cursor.py) |
| Stampede sem furar a quota? | [cache.py](src/api_sentinel/cache.py) |
| Cancelar SQL e conter ERP lento? | [telemetry.py](src/api_sentinel/telemetry.py), [erp.py](src/api_sentinel/erp.py) |
| Alertar com a API parada? | [probe.py](alert_receiver/probe.py), [regras](monitoring/rules), [SLO](docs/slo.md) |

[Arquitetura](docs/architecture.md) · [demo](docs/demo.md) · [decisões técnicas](docs/decisoes-tecnicas.md).

## Limites

A quota é janela fixa, então dá burst na fronteira. As duas réplicas coordenam, mas não são cluster distribuído. O dataset é fixo e versionado; o TTL de cache não promete consistência forte pra escrita futura. O SLO de 30 dias é referência, não resultado de uma demo curta. Traces com amostragem de 25% e retenção em memória. O host inteiro é ponto único de falha, inclusive pro monitoramento. O CI está pronto mas não rodou no GitHub porque não publiquei; por isso sem badge.

Python, FastAPI, PostgreSQL, Redis, NGINX, Prometheus/Grafana/Jaeger. Licença MIT.
