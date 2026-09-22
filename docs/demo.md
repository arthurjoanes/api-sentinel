# Demonstração operacional

O cliente da API é uma integração de lojas; o operador precisa reconhecer falha, encontrar a dependência envolvida e confirmar recuperação. Dados comerciais e ERP são sintéticos. PostgreSQL, Redis, proxy, regras e entrega de alertas são executados localmente.

A [verificação atual](verification.md) e a [prova completa de 22/09 às 12:12 UTC](evidence/editorial-20260922/full-run.json) identificam a imagem e os resultados desta revisão. A [sequência de capturas das 12:49 UTC](evidence/editorial-20260922/capture-run.json) usa outra imagem, com sincronização do coletor corrigida, e não repete o benchmark. O roteiro abaixo pode ser repetido em um projeto Docker descartável.

Para acompanhar um exemplo já executado, veja a [consulta conhecida, incidente e recuperação](operational-story.md), com três capturas reais e observações da mesma execução. Esse cenário limitado tem identidade própria e não substitui a prova completa de carga.

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
4. Incidente e recuperação (2 min). Abra Incidentes na central da execução mantida e selecione Finalizados. Confira o estado Resolvido; um encerramento pelo operador tem indicação própria e não comprova recuperação recebida. Mostre a ocorrência real de perda de réplica e a de indisponibilidade total; abra a ocorrência para ver impacto, ação recomendada e a cronologia de entregas; depois abra o runbook. `alerts-real.json` contém firing/resolved da mesma ocorrência, tempos monotônicos e coleta posterior à recriação. O teste permite 90 s por transição; scrape, persistência e agrupamento explicam a espera.
5. Investigar e limitar a conclusão (1 min). Abra Métricas · Grafana pelos links da central e o trace registrado em `trace-correlation.json` no Jaeger. Compare duração total, aquisição de pool, SQL, cache e ERP. A amostragem de 25% não garante um trace para toda requisição. Duas réplicas locais não demonstram disponibilidade entre máquinas, capacidade máxima ou SLO de 30 dias.

Os passos 2–3 usam artefatos da execução completa; `--scenario alerts` não os produz. A central não transforma ausência de incidentes em sinal de saúde: valide o probe, os targets e a fixture final.

## Exercício com outra pessoa — preparado, ainda não realizado

O roteiro técnico anterior demonstra mecanismos. Para descobrir se alguém consegue operar a aplicação sem orientação contínua do autor, use o exercício abaixo em um ambiente descartável já preparado. Não se trata de um piloto comercial, teste de disponibilidade mensal ou experiência de contratação.

1. Entregue o contexto: uma integração consulta vendas e pode perder uma réplica. Informe a URL da central, a organização fictícia, a consulta de referência e a identidade exata do projeto da execução.
2. Peça à pessoa que encontre o total e explique a diferença entre três itens e dois pedidos. Registre o resultado obtido e qualquer ajuda fornecida.
3. O responsável pelo ambiente executa a falha controlada do roteiro; o participante localiza a ocorrência e indica quais sinais conferiria antes de atribuir uma causa. Ele não precisa receber credenciais administrativas nem executar comandos destrutivos.
4. Depois da restauração pelo responsável, peça que confirme a consulta de R$ 125,00, a quantidade esperada de réplicas e a recuperação recebida na mesma ocorrência. Uma ação “encerrar” não vale como prova de recuperação.
5. Registre, sem dados pessoais, quais etapas foram concluídas, onde houve dúvida, ajuda recebida e tempo observado. Preserve também uma tentativa malsucedida. Não anuncie redução de tempo sem uma comparação realizada sob condições declaradas.

Antes de executar qualquer comando de runbook, confira o contexto: os exemplos dos procedimentos usam `pf-api-sentinel`, a demonstração persistente. Em uma revisão, o responsável deve usar o projeto e os arquivos Compose registrados em `run.json`, sem copiar o nome do exemplo. A navegação para Grafana/Jaeger/Prometheus resolve as URLs da execução, mas isso não muda automaticamente o texto dos comandos do runbook.

Registro mínimo proposto para uma sessão: data, fontes/imagem, ID da execução, tarefas, resultados, intervenções, dúvidas e limite da conclusão. A sessão só pode ser descrita como realizada após existir esse registro. Se a pessoa não conseguir concluir, o próximo incremento é corrigir a orientação ou a interface correspondente e repetir a tarefa; acrescentar ferramentas não resolve automaticamente a dificuldade observada.

## Encerrar uma execução preservada

Copie o caminho exato de `run.json` produzido por `--keep`. O comando de limpeza foi gerado para aquele projeto:

```powershell
$SentinelRunFile = (Resolve-Path -LiteralPath 'artifacts/problem-review/<UTC>/run.json').Path
$SentinelRun = Get-Content -LiteralPath $SentinelRunFile -Raw | ConvertFrom-Json
$SentinelCleanup = @($SentinelRun.cleanup_command)
if ($SentinelCleanup.Count -lt 2 -or $SentinelCleanup[0] -ne 'docker') { throw 'Comando de limpeza ausente.' }
$SentinelPreviousRunDir = [Environment]::GetEnvironmentVariable('SENTINEL_RUN_DIR', 'Process')
try {
    $env:SENTINEL_RUN_DIR = Split-Path -Parent $SentinelRunFile
    & docker @($SentinelCleanup[1..($SentinelCleanup.Count - 1)])
    if ($LASTEXITCODE -ne 0) { throw 'A limpeza falhou.' }
} finally {
    [Environment]::SetEnvironmentVariable('SENTINEL_RUN_DIR', $SentinelPreviousRunDir, 'Process')
}
```

`SENTINEL_RUN_DIR` é obrigatório para o Compose interpretar os mounts do ensaio, inclusive ao encerrar; o exemplo restaura seu valor anterior ao terminar. Mantenha disponíveis os arquivos Compose identificados pelo comando gerado. Isso remove os volumes descartáveis daquela execução; os artefatos no projeto permanecem. Não execute comandos genéricos de prune. A demonstração persistente pode ser iniciada por `scripts/sentinel.ps1 start -Replicas 2` e encerrada por `stop`, que preserva os volumes dela.

## Instalação persistente no Linux

Este é o ambiente local de exploração. Para injetar falhas e remover volumes ao terminar, use o runner isolado descrito no início; não adapte os comandos de limpeza para esta stack.


```sh
docker compose -f compose.yml build api
docker compose -f compose.yml up -d --wait postgres redis
docker compose -f compose.yml run --rm -e REPLICAS=2 tools python scripts/bootstrap.py
docker compose -f compose.yml run --rm tools python -c 'import json; from pathlib import Path; p=Path("/secrets/public-urls.json"); p.write_text(json.dumps({"grafana":"http://127.0.0.1:3104","jaeger":"http://127.0.0.1:16684","prometheus":"http://127.0.0.1:9104","alertmanager":"http://127.0.0.1:9194"})); p.chmod(0o644)'
docker compose -f compose.yml --profile observability up -d --scale api=2
umask 077
mkdir -p .runtime
docker compose -f compose.yml cp --index 1 api:/secrets/demo.json .runtime/demo.json
```

Todos os serviços publicados ficam em loopback:

| Serviço | Endereço |
| --- | --- |
| Central de incidentes e runbooks | [localhost:9184](http://127.0.0.1:9184/) |
| API e Swagger | [localhost:8104/docs](http://127.0.0.1:8104/docs) |
| Grafana | [localhost:3104](http://127.0.0.1:3104/d/sentinel/api-sentinel) |
| Jaeger | [localhost:16684](http://127.0.0.1:16684/) |
| Coleta por réplica | [localhost:9104/targets](http://127.0.0.1:9104/targets) |
| Alertmanager | [localhost:9194](http://127.0.0.1:9194/) |

Os tokens ficam em `.runtime/demo.json`, ignorado pelo Git. Exemplo de consulta em PowerShell:

```powershell
$tokens = Get-Content .runtime/demo.json -Raw | ConvertFrom-Json
Invoke-RestMethod 'http://127.0.0.1:8104/v1/stores/1/summary?start=2026-01-01&end=2026-01-31' -Headers @{Authorization="Bearer $($tokens.tenant_a)"}
```

A massa comercial cobre 01/01 a 01/03/2026, inclusive. A loja 7 pertence ao tenant técnico e cobre somente 01/01/2026. Para conferir um resultado conhecido, use seu token próprio:

```powershell
$referencia = Invoke-RestMethod 'http://127.0.0.1:8104/v1/stores/7/summary?start=2026-01-01&end=2026-01-01' -Headers @{Authorization="Bearer $($tokens.probe)"}
$referencia | Select-Object revenue_cents, order_count, average_ticket_cents
# Esperado: 12500, 2, 6250 — R$ 125,00 em dois pedidos, ticket de R$ 62,50.
```

Esses valores vêm de três itens definidos na [fixture](../data/fixtures/manual-sales.json), conferidos por uma [conta independente](../tests/unit/test_data_contract.py). O token A não tem acesso à loja 7. O [contrato de dados](data-contract.md) define escopo, cobertura e paginação.
