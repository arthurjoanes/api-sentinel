# Indicadores, objetivos e alertas

Os objetivos de referência são 99,9% de disponibilidade das requisições elegíveis observadas pela aplicação e 95% das respostas bem-sucedidas elegíveis abaixo de 500 ms, em janela móvel de 30 dias. São hipóteses de engenharia para este laboratório; minutos de demonstração não mostram cumprimento mensal. A definição de latência considera sucessos separadamente para impedir que rejeições rápidas aparentem melhoria.

## Fontes e população

| Indicador | Numerador | Denominador / população | Limitação |
|---|---|---|---|
| Disponibilidade da aplicação | Respostas `success` | `success + server_error`, tráfego `business`, rotas stores/summary/sales | Não observa conexões nem 503 gerados antes da API |
| Latência de sucesso | Bucket `le="0.5"` com `outcome="success"` | Count do mesmo histograma e população | Limite inclusivo do bucket: ≤500 ms; objetivo informal “abaixo” usa esse limite operacional |
| Consulta pelo proxy | Execução autenticada com status, schema e fixture corretos | Execuções do probe externo ao processo API | Amostragem a cada 3 s, não todas as requisições de clientes |
| Réplicas disponíveis | Soma de `up{job="api"}` | Gauge `sentinel_expected_replicas` do receiver | Disponibilidade de coleta não indica correção da consulta |
| Coleta e entrega | Targets, último probe, notificações e webhooks persistidos | Séries independentes da aplicação | Falha de todo o computador também derruba a supervisão local |

`server_error` inclui 503 por saturação, falha de aquisição e Redis indisponível. `quota` identifica exclusivamente 429 da quota contratada; aparece em painel próprio, fora do denominador de disponibilidade. Erros de cliente, como credencial inválida ou cursor recusado, também ficam fora desse denominador. O ERP opcional tem seus próprios indicadores e alerta warning; não altera o SLI de resumos e vendas. O probe usa `traffic="probe"`, tenant e credencial próprios, sem disputar a quota do tenant sob carga.

Os filtros PromQL selecionam `/v1/stores` e `/v1/stores/.*/(summary|sales)` sobre rotas normalizadas, nunca sobre a URL bruta. Histogramas combinam buckets de todas as réplicas antes de calcular percentis. Não se calcula média de p95 individuais. Labels não incluem tenant, loja, SKU, token, request_id ou trace_id.

Sem tráfego, o denominador é zero e o indicador é indefinido. Sem séries, não há indicador. Os painéis preservam essa diferença com lacunas/“Sem dados”; não usam `or vector(1)` para inventar saúde. Somente a contagem de réplicas utiliza zero quando não há targets, porque o número esperado vem de uma fonte independente. `sentinel_probe_last_run_timestamp_seconds` detecta um probe travado mesmo quando o endpoint de métricas do receiver continua respondendo.

## Dois conjuntos mutuamente exclusivos

`monitoring/prometheus/demo.yml` carrega somente `rules/demo.yml`; `reference.yml` carrega somente `rules/reference.yml`. A configuração correspondente do Alertmanager precisa ser escolhida na mesma execução. Não carregue ambos por glob. Cada regra carrega `project=api-sentinel`, `service=api-sentinel` e `environment=demo|reference`, além da severidade.

| Configuração | Scrape / avaliação | Persistência `for` | Agrupamento inicial / mudanças / repetição |
|---|---|---|---|
| Demo | 5 s / 5 s | 15 s | 5 s / 10 s / 5 min |
| Referência | 15 s / 30 s | 2 min | 30 s / 5 min / 4 h |

O DNS é atualizado a cada 5 s nos dois conjuntos. Recriar uma réplica pode mudar seu IP; o Prometheus descobre o nome `api` por registros A, porta interna 8000, e coleta cada endereço. Coletar apenas o proxy perderia a identidade das instâncias. Se o DNS retirar uma réplica, sua série desaparece: por isso `SentinelReplicaLost` compara a soma dos targets disponíveis com o gauge independente de quantidade esperada, em vez de depender apenas de `up == 0`.

## Orçamento de erro

A fração permitida é `1 - 0,999 = 0,001`. Para uma janela W:

```text
error_ratio_W = rate(5xx observados em W) / rate(requisições elegíveis em W)
burn_rate_W  = error_ratio_W / 0,001
orçamento consumido ≈ burn_rate × duração da janela / 30 dias
```

As recording rules aplicam `rate`/`increase` a cada série antes de somar, respeitando resets dos contadores. A ausência de série de erro vira zero somente quando existe denominador de requisições. Denominador ausente ou zero permanece indefinido.

A regra de referência usa duas alternativas, cada uma com confirmação longa e curta:

```text
(burn_1h > 14,4 E burn_5m > 14,4 E volume_1h ≥100 E volume_5m ≥20)
OU
(burn_6h > 6 E burn_30m > 6 E volume_6h ≥100 E volume_30m ≥20)
```

14,4 durante uma hora corresponde a aproximadamente 2% do orçamento mensal; 6 durante seis horas corresponde a 5%. As janelas curtas permitem encerrar o alerta após a recuperação sem esperar toda a janela longa. Os mínimos 100/20 são limites explícitos do laboratório, ajustáveis com tráfego real: baixa demanda pode consumir orçamento sem disparar este alerta. O probe continua supervisionando a jornada nesse caso. Uma instalação recém-iniciada não tem histórico mensal; uma taxa sobre a parte disponível da janela não cria esse histórico.

Na demo, o mesmo alerta usa mais de 5% de erros em 2 min e 30 s, com pelo menos 20 e 5 requisições e `for=15s`. Isso equivale a burn maior que 50 para o objetivo de 99,9%, mas é um limiar didático curto; não redefine o SLO de 30 dias. A regra operacional permanece separada e é testada com séries sintéticas longas.

## Sintomas e ações

| Alerta | Condição | Primeira ação |
|---|---|---|
| `SentinelUnavailable` | Probe autenticado persistentemente falha | Conferir proxy, réplicas e dependências; validar fixture após restaurar |
| `SentinelErrorBudgetBurn` | Erro acima dos limiares longo e curto com volume | Correlacionar 503/5xx com admissão, pools e Redis |
| `SentinelLatencyHigh` | Mais de 5% de sucessos excedem 500 ms; mínimo 20/1 min demo ou 100/10 min referência | Comparar espera de pool, SQL, cache e trace |
| `SentinelSaturation` | Rejeições com ocupação elevada, ou timeout de aquisição | Reduzir carga e conferir o orçamento de conexões |
| `SentinelReplicaLost` | Targets disponíveis menores que o esperado | Restaurar réplica e verificar redescoberta DNS |
| `SentinelTelemetryUnavailable` | Coleta necessária ausente/falhando, probe atrasado ou ≥3 falhas de entrega na janela | Recuperar observação e entrega; ausência de erros não indica saúde |
| `SentinelERPUnavailable` | Circuito de pelo menos uma réplica permanece aberto | Verificar ERP e confirmar que resumos continuam úteis |

O alerta de saturação combina rejeições com ao menos um destes sinais: entrada ≥40, autenticação ≥3, negócio ≥8 ativos, pool de dados ≥3 ou pool de autenticação ≥2 conexões em uso. Usa máximo observado em 1 min (demo) ou 5 min (referência). Timeout de pool já indica espera frustrada e também dispara. Ocupação elevada isolada não alerta. O uso de amostras significa que picos muito curtos de ocupação podem não ser capturados.

Cada alerta contém resumo, impacto, condição, janela, ação, dashboard e runbook. A UI mostra estado e tempos reais; valores variáveis não entram na identidade. O agrupamento usa projeto/ambiente/serviço/alerta. Esta cadeia local não aplica inibição: no teste real, ela suprimiu uma recuperação de perda de réplica já entregue, deixando a caixa divergente do estado observado. Agrupamento, persistência e cadência controlam o ruído sem omitir deliberadamente transições. O registro anterior à retirada da inibição está em [alerts-before-inhibition-fix.json](../artifacts/alerts-before-inhibition-fix.json).

Alertmanager autentica o webhook por arquivo separado, utiliza timeout de 5 s e `send_resolved=true`. O receiver persiste antes de responder; reentregas são esperadas e não significam novas ocorrências. Sua chave é fingerprint + início. Uma recuperação antiga não encerra incidente novo, e firing atrasado não reabre ocorrência resolvida. Consulte o contrato/retencão do receiver para limites do histórico; não há garantia de entrega exatamente uma vez.

## Prazos e testes

Para indisponibilidade na demo, reserve até 90 s para firing persistido e até 90 s para resolved depois da restauração. A composição típica saudável é: probe até 3 s, scrape até 5 s, primeira avaliação até 5 s, `for` 15 s, próximo ciclo até 5 s e agrupamento até 5 s. Mudanças em grupo existente podem esperar até 10 s. Esses limites incluem margem de agendamento local e não prometem entrega se receiver, Prometheus ou Alertmanager estiverem indisponíveis. Burn e latência precisam também formar/esvaziar suas janelas: use até 180 s no teste demo. Aguarde estado real por polling com deadline; não substitua isso por sleep fixo.

Validação sintática e das séries sintéticas, no PowerShell:

```powershell
./scripts/sentinel.ps1 check
```

`check` roda Ruff, formato, mypy e `scripts/check_monitoring.py`, o mesmo script usado pelo CI. Ele executa `promtool check config`, `check rules`, `test rules` e `amtool check-config`. São 47 casos: 26 demo, 13 de referência, quatro de coleta/entrega e quatro de frescor; os oito adicionais avaliam ambos os perfis. Cobrem estado saudável, pico curto, falha sustentada, recuperação, série ausente, volume insuficiente, contador reiniciado, réplica removida/reaparecida, 429 separado, probe separado, ERP separado, pool, ocupação sem impacto, probe travado e configuração inválida ou ausente. Também cobrem autoscrape com target presente mas `up=0`, falhas repetidas de entrega com scrapes saudáveis, erro único sem ruído, contador histórico, intervalo de probe longo e relógio futuro. Os arquivos incluem expectativas de labels/annotations e resultados PromQL, não apenas parse da expressão.

O receiver publica `sentinel_probe_stale_after_seconds`, derivado do intervalo/deadline configurados. As regras usam `max(30 s, limite configurado)` na demo e `max(60 s, limite configurado)` na referência; o piso preserva a margem para coleta/avaliação. Se uma instalação anterior não exporta o gauge, permanece o piso do perfil. Um timestamp futuro aciona falha de observação e impede classificar uma resposta antiga como indisponibilidade atual. A UI pode marcar a leitura desatualizada antes do alerta persistir; os dois tempos têm finalidades diferentes.

Esses testes já foram executados com Prometheus 3.5.0 e Alertmanager 0.28.1. Eles não testam entrega de rede. O aceite operacional exige a sequência real documentada em `docs/verification.md`: falha controlada → firing no Prometheus → entrega/persistência no receiver sem duplicação → restauração → resolved → probe correto e targets recuperados. Repita com todas as APIs paradas, mantendo o receiver independente. Um alerta resolvido sem probe recuperado pode indicar perda de observação; valide ambos.

O dashboard provisionado tem UID `sentinel` e fontes Prometheus/Jaeger. Abra `http://localhost:3104/d/sentinel/api-sentinel`, selecione o intervalo do incidente, compare latência com espera de pool/cache e abra Jaeger no mesmo período. O trace_id conecta a investigação aos logs JSON.

## Fontes oficiais

- [Google SRE: alertas multiwindow/multi-burn-rate](https://sre.google/workbook/alerting-on-slos/).
- [Prometheus: descoberta DNS](https://prometheus.io/docs/prometheus/latest/configuration/configuration/#dns_sd_config) e [redes Compose](https://docs.docker.com/compose/how-tos/networking/).
- [Prometheus: regras e persistência](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/), [testes sintéticos](https://prometheus.io/docs/prometheus/latest/configuration/unit_testing_rules/) e [histogramas agregáveis](https://prometheus.io/docs/practices/histograms/).
- [Alertmanager: agrupamento, inibição e webhook](https://prometheus.io/docs/alerting/latest/configuration/).
