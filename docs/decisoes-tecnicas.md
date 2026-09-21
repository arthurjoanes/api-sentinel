# Decisões técnicas

Uma integração precisa obter vendas corretas e disponibilidade de produtos sem misturar organizações. Quando o ERP degrada, o operador precisa distinguir essa falha da perda da API ou do banco e confirmar a volta do resultado conhecido. O projeto demonstra esse comportamento em laboratório; utilidade com operadores reais e benefício comercial não foram medidos.

## Acompanhar uma consulta

Leia `app.py`, `auth.py`, `admission.py`, `cache.py`, `queries.py` e `db.py` nessa ordem. Uma consulta de resumo entra pelo NGINX e passa por admissão global imediata. A autenticação usa pool separado e prazo curto. A credencial determina tenant, lojas e escopos; o cliente não escolhe sua identidade por query string. Só depois da autorização entram quota Redis, admissão local de negócio e cache/SQL.

A receita soma quantidade × preço em centavos. Pedidos distintos usam `(store_id, order_id)`, não a quantidade de itens. O ticket médio arredonda `revenue/order_count` com Decimal e HALF_UP. O período é um intervalo de dias comerciais de São Paulo convertido para UTC semiaberto, e não um filtro por datas UTC. A fixture de três itens e dois pedidos torna esses erros visíveis sem depender do gerador para calcular o resultado esperado.

Vendas usam cursor com ordenação decrescente por `(sold_at, id)` e desempate único. O SQL busca no máximo `limit+1`, sem trazer toda a tabela. O cursor assinado carrega tenant, loja, período e versão dos dados; não é SQL nem credencial. Assinatura não torna o conteúdo secreto. A versão imutável do dataset define o contrato durante a paginação; avançar a versão invalida cursores antigos.

## Comportamento da API

| Pergunta | Resposta específica deste projeto |
|---|---|
| Onde medir antes de otimizar? | Aquisição de conexão, execução SQL, Redis, HTTP ERP e duração total. Examine EXPLAIN da consulta real antes de atribuir tudo ao framework. |
| Async torna o sistema ilimitado? | Não. Conexões, tarefas, memória e tempo são finitos. Async permite aguardar I/O sem bloquear o loop; a admissão impede multiplicar trabalho além do limite. |
| Por que o pool não basta? | Um pool limita conexões, mas milhares de requests podem esperar por elas. A admissão deste projeto rejeita imediatamente antes de formar uma fila ilimitada. |
| Quota e concorrência são a mesma coisa? | Quota controla chegadas por tenant no Redis; concorrência limita trabalho simultâneo no processo. ERP lento pode esgotar concorrência mesmo com poucas chegadas. |
| O que significa 429 ou 503? | 429 indica quota contratada excedida. 503 indica saturação ou dependência indisponível. Usar 429 para toda rejeição esconderia falta de capacidade no SLI. |
| Duas réplicas dobram a quota? | Não. Ambas usam a mesma chave/execução atômica Redis por tenant. Já os limites de concorrência e pools são locais e se multiplicam. |
| Qual é o orçamento do banco? | Por processo: 4 conexões de negócio + 2 de autenticação, sem overflow. Duas réplicas somam 12; ferramentas, diagnóstico e reservas entram no orçamento até max_connections=40. |
| Qual o risco do cache multi-tenant? | Uma chave incompleta pode servir dados privados de outra loja. A autorização vem antes do lookup; a chave inclui versão, tenant, loja e filtros normalizados. |
| Como demonstrar stampede controlado? | Compare cache frio, quente e expiração simultânea por número de consultas SQL e contenção de preenchimento. Latência menor sozinha não indica redução de carga. |
| Por que o lock tem token e TTL? | O TTL limita a vida do lock após falha. A remoção condicional pelo token impede um processo atrasado de apagar o lock de outro dono. A espera pelo preenchimento tem prazo. |
| O que acontece quando Redis cai? | A quota falha fechada com 503. O fallback limitado do cache só se aplica quando a quota ainda funciona. Redis inteiro indisponível não pode liberar carga irrestrita no banco. |
| Por que read timeout não basta no ERP? | Um servidor pode enviar pequenos trechos periodicamente e evitar o timeout de leitura. O deadline total encerra o orçamento mesmo com progresso parcial. |
| O circuito é global? | É por processo. Cada réplica mantém falhas e probe de recuperação próprios. O estado só protege o ERP, sem transformar sua falha em indisponibilidade de consultas PostgreSQL. |
| Como evitar SSRF? | O destino vem da configuração confiável. O consumidor envia loja/SKU validados; não fornece URL, Host ou credencial de saída. Redirects e proxies herdados ficam desabilitados. |
| Como evitar ruído de alerta? | Use persistência, janelas, volume mínimo, agrupamento e relação com impacto. Ocupação elevada sozinha não é o mesmo que rejeição de trabalho. |

O rate limiter usa janela fixa de 1000 ms iniciada no primeiro acesso, por chave de tenant. O script Redis executa INCR/PEXPIRE/PTTL atomicamente. Isso permite rajadas na fronteira entre janelas; não equivale a um limite contínuo em qualquer intervalo móvel de um segundo. A justiça por tenant da admissão também é local, não um escalonador global entre containers.

O cache tem TTL de 15 s e dados versionados. `data_updated_at` representa a massa; `observed_at`, o cálculo; `cache_age_seconds` mostra a idade desse cálculo. Um hit não torna os dados mais novos. Se o sistema passar a aceitar escrita, será preciso definir transação, invalidação e tolerância a dados antigos.

## Investigar incidentes

O caminho completo é probe → Prometheus → regra persistente → Alertmanager → webhook autenticado → transação SQLite → UI. O probe tem tenant próprio e verifica status, schema e resultado conhecido pelo proxy. Assim, o alerta continua observando a jornada quando o processo da API para, e um tenant sob quota não produz falso alerta de indisponibilidade.

O receiver identifica ocorrências por fingerprint e startsAt. Repetições atualizam a mesma ocorrência; um firing atrasado não reabre a que já resolveu. Uma recuperação antiga não encerra uma ocorrência nova. Isso é idempotência da recepção, sem garantia de entrega exatamente uma vez. O histórico e as notificações dependem dos volumes/serviços locais.

Durante um pico de latência, compare: duração total de sucesso → aquisição de conexão → SQL → cache → ERP → event-loop. Uma query curta depois de espera longa sugere pressão anterior ao SQL; cache miss e aumento de queries apontam outra hipótese. Abra um trace existente no intervalo e busque seu trace_id nos logs. A amostragem de 25% limita a cobertura; a ausência de trace individual não significa que a requisição não existiu.

O alerta informa um sintoma e uma ação inicial. `SentinelSaturation` combina rejeição/ocupação ou timeout de pool; não diagnostica sozinho qual consulta é culpada. A restauração exige probe correto e targets recuperados, além do estado resolved no receiver. “Não há séries” e “não houve tráfego” são estados diferentes de “saudável”.

Leia [slo.md](slo.md) para a população elegível e o cálculo: a disponibilidade interna exclui 429 contratado e erros do cliente, mas inclui 503. O contador da API não vê falhas que o proxy produz sem encaminhar a chamada. O probe e o cliente de carga oferecem medições separadas desse caminho. O SLO de 30 dias não é validado por uma demonstração de minutos.

## Aplicar a sistemas de lojas

Em uma aplicação existente, comece pelo fluxo que precisa preservar: autorização, precisão do agregado e limites de consumo. Defina população, fonte e denominador do indicador antes de escolher um gráfico. Meça a aquisição de conexão separada do SQL e escolha índices alinhados a tenant/loja/período/ordenação. Dimensione pools considerando todas as réplicas, processos e ferramentas.

Depois defina comportamento sob excesso: fila pequena com prazo ou rejeição imediata; quota global ou local; dependências que precisam falhar fechadas. Acrescente cache somente com chave e frescor explícitos. Para integrações, mantenha cliente reutilizado, pool limitado, deadline total, validação de resposta e retries centralizados. Cada proteção deve ter um experimento que revele seu efeito e uma forma clara de recuperação.

## Mapeamento conceitual para Azure e KQL

Nenhuma integração Azure foi configurada ou executada neste projeto. O mapeamento abaixo serve para estudar como os conceitos podem se relacionar ao contexto de Log Analytics/KQL. Exportação, identidade, amostragem, custo e retenção precisariam de desenho e validação próprios.

| No laboratório | Correspondência conceitual possível |
|---|---|
| Requests e spans de dependência OpenTelemetry | Application Insights, `AppRequests` e `AppDependencies`, correlacionados por OperationId |
| Logs JSON com IDs | Logs no workspace com schema e retenção definidos; correlação ao identificador de operação |
| Dashboard Grafana | Grafana/Workbooks conforme a fonte escolhida e a necessidade de investigação |
| Regras PromQL | Regras para métricas Prometheus gerenciadas, ou outra regra equivalente cuja semântica seja revalidada |
| Regra + receiver local | Alertas e grupos de ação; payload, autenticação, repetição e recuperação exigem adaptação |

As tabelas oficiais têm `DurationMs`, `ResultCode`, `OperationId` e `ItemCount`; este último representa quantos itens uma amostra representa. `TenantId` nessas tabelas identifica o workspace Log Analytics, não o tenant comercial do Sentinel. Consulte [AppRequests](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/apprequests) e [AppDependencies](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/tables/appdependencies).

Exemplo conceitual de investigação, se existisse ingestão no Application Insights. As propriedades `http.route` e `traffic` abaixo seriam um contrato de mapeamento a implementar; não são exportadas para Azure pelo projeto:

```kusto
AppRequests
| where TimeGenerated > ago(30m) and AppRoleName == "api-sentinel"
| extend Route = tostring(Properties["http.route"]),
         Traffic = tostring(Properties["traffic"]),
         Code = toint(ResultCode), Weight = coalesce(ItemCount, 1)
| where Traffic == "business"
| where Route in ("/v1/stores", "/v1/stores/{store_id}/summary", "/v1/stores/{store_id}/sales")
| where Code between (200 .. 399) or Code between (500 .. 599)
| summarize Eligible = sum(Weight), Errors = sumif(Weight, Code >= 500)
    by bin(TimeGenerated, 1m)
| extend ObservedAvailability = 1.0 - todouble(Errors) / Eligible
```

Não converta períodos sem linhas em 100%. Contagens ponderadas por amostragem são estimativas e não substituem automaticamente um contador de todas as requisições para SLO. Seria preciso validar a estratégia de coleta.

Para investigar as dependências da requisição lenta mais recente no período:

```kusto
let SlowOperation = AppRequests
    | where TimeGenerated > ago(30m) and AppRoleName == "api-sentinel"
    | where DurationMs > 500
    | top 1 by TimeGenerated desc
    | project OperationId;
AppDependencies
| where TimeGenerated > ago(30m)
| where OperationId in (SlowOperation)
| project TimeGenerated, OperationId, DependencyType, Name, Target, DurationMs, Success
| order by TimeGenerated asc
```

O vínculo requests/dependências é documentado em [Dependency tracking](https://learn.microsoft.com/en-us/azure/azure-monitor/app/dependencies). Para alertas, a escolha entre métricas, consultas de logs e Prometheus depende da fonte e das janelas necessárias; [tipos de alerta](https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/alert-options) e [grupos de ação](https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/action-groups) são referências conceituais.
