# Demonstração operacional

O cliente da API é uma integração de lojas; o operador precisa reconhecer falha, encontrar a dependência envolvida e confirmar recuperação. Dados comerciais e ERP são sintéticos. PostgreSQL, Redis, proxy, regras e entrega de alertas são executados localmente.

Execução de referência aprovada: [20260921t064944662185z](../artifacts/problem-review/20260921t064944662185z/summary.json). Ela contém a matriz completa, duas réplicas com quota compartilhada, falhas recuperadas e alertas entregues/resolvidos. [Verificação](verification.md) distingue a imagem medida, o ajuste posterior no registro de limpeza e a atualização da demonstração principal.

## Preparar a execução

Use Docker Desktop com containers Linux, Compose 2.24.4+ e Python 3.11+ no host. Na raiz deste projeto:

```powershell
python scripts/review.py
if ($LASTEXITCODE -ne 0) { throw 'A revisão falhou; veja o diretório indicado.' }
```

O comando constrói a imagem, executa checks/testes e cria `pf-api-sentinel-review-<UTC>` com rede, banco, tokens e volumes próprios. As portas são temporárias e publicadas somente em loopback. Nenhuma falha é injetada na stack persistente `pf-api-sentinel`. Reserve a janela exclusivamente para este teste; não execute outra carga ao mesmo tempo.

Cada execução grava `artifacts/problem-review/<UTC>/run.json`, logs, conferência por linhas brutas (`oracle.json`) e resultados separados. Falhas preservam seus artefatos e encerram os recursos descartáveis. Um resultado aprovado inclui restauração e comparação dos IDs dos containers da demonstração antes/depois. O tempo de preparação depende do download/build; não faz parte do roteiro de apresentação abaixo.

Para inspecionar o painel ao vivo depois dos ciclos de alerta:

```powershell
python scripts/review.py --scenario alerts --keep
```

Essa variante executa checks, testes, dois ciclos reais de incidentes e correlação, sem a matriz de carga/falhas de dependências. `--keep` preserva somente uma execução aprovada. Abra as URLs impressas ou registradas em `run.json.urls`; não use as portas da demonstração persistente. Os links de investigação da central resolvem para esses mesmos serviços.

## Apresentação de 5–8 minutos

1. Problema e resultado correto (1 min). Mostre `fixture_final`: 12.500 centavos, dois pedidos, ticket 6.250. A fixture tem três itens e dois pedidos, portanto contar linhas daria o resultado errado. Em `oracle.json`, explique que totais e primeiros itens foram calculados a partir das linhas SQL, independentemente do agregado da API. A suíte HTTP verifica IDs válidos de outro tenant e cache aquecido.
2. Falha sem contaminação (2 min). Compare `load-mixed-normal.json`, `load-mixed-erp-degraded.json` e `load-mixed-recovered.json`. A mistura e oferta são pré-definidas. Mostre respostas comerciais corretas, erros esperados exclusivamente no ERP, iterações iniciadas/concluídas e drops. Apresente percentis de sucesso separados das rejeições; p95 global menor com 503 rápidos não seria melhoria.
3. Quota e banco (1 min). Compare `quota-one`/`quota-two`: mais réplicas não devem duplicar a quota. Em `tenant-isolation`, mostre os denominadores completos dos dois tenants. `run.json.cache` registra quatro chamadas por fase e SQL 1/0/1; Redis inteiro parado deve retornar 503 sem novo SQL de resumo. Isso difere da indisponibilidade somente do cache, que permite fallback limitado.
4. Incidente e recuperação (2 min). Abra a central da execução mantida e filtre resolvidos. Mostre a ocorrência real de perda de réplica e a de indisponibilidade total; abra o histórico e o runbook. `alerts-real.json` contém firing/resolved da mesma ocorrência, tempos monotônicos e coleta posterior à recriação. O teste permite 90 s por transição; scrape, persistência e agrupamento explicam a espera.
5. Investigar e limitar a conclusão (1 min). Abra Grafana pelos links da central e o trace registrado em `trace-correlation.json` no Jaeger. Compare duração total, aquisição de pool, SQL, cache e ERP. A amostragem de 25% não garante um trace para toda requisição. Duas réplicas locais não demonstram disponibilidade entre máquinas, capacidade máxima ou SLO de 30 dias.

Os passos 2–3 usam artefatos da execução completa; `--scenario alerts` não os produz. A central não transforma ausência de incidentes em sinal de saúde: valide o probe, os targets e a fixture final.

## Encerrar uma execução preservada

Copie o caminho exato de `run.json` produzido por `--keep`. O comando de limpeza foi gerado para aquele projeto:

```powershell
$SentinelRun = Get-Content -LiteralPath 'artifacts/problem-review/<UTC>/run.json' -Raw | ConvertFrom-Json
$SentinelCleanup = @($SentinelRun.cleanup_command)
if ($SentinelCleanup.Count -lt 2 -or $SentinelCleanup[0] -ne 'docker') { throw 'Comando de limpeza ausente.' }
& docker @($SentinelCleanup[1..($SentinelCleanup.Count - 1)])
if ($LASTEXITCODE -ne 0) { throw 'A limpeza falhou.' }
```

Isso remove os volumes descartáveis daquela execução; os artefatos no projeto permanecem. Não execute comandos genéricos de prune. A demonstração persistente pode ser iniciada por `scripts/sentinel.ps1 start -Replicas 2` e encerrada por `stop`, que preserva os volumes dela.
