# Central e detalhe

As imagens mostram a central local com dados sintéticos de referência de 12/10/2026, 06:00 UTC. O probe está desativado nesta prévia; os gráficos e a cronologia apresentam registros de exemplo, sem executar falha ou recuperação da API. Consulte o [guia da central](incident-console.md) para interpretar os dados.

## Central

![Central com totais retidos, inícios por dia e fila de ocorrências](readme/incidents.png)

Os totais incluem todos os estados retidos. Os inícios por dia usam somente a amostra carregada pelo filtro, nos sete dias UTC indicados.

## Detalhe

![Ocorrência ativa com período registrado, impacto, runbook e histórico de entregas](readme/incident-detail.png)

O período informado pelo alerta aparece separado dos horários de recebimento das entregas. Origem, interpretação e identificação ficam disponíveis por expansão.

A [conta comercial](readme/commercial-fixture.svg) usa os valores da [fixture independente](../data/fixtures/manual-sales.json); o [mapa de arquitetura](readme/architecture.svg) mostra os componentes no mesmo host. Para uma sequência operacional já executada, veja [consulta, falha e recuperação de 22/09/2026](operational-story.md), com seus registros técnicos e imagens originais.
