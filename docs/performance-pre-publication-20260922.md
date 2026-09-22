# Desempenho e falhas observados

## Execução de 21/09/2026, 06:49–06:57 UTC

Fonte: [execução completa](../artifacts/problem-review/20260921t064944662185z/run.json), [resumo derivado](../artifacts/problem-review/20260921t064944662185z/summary.json) e load-*.json no mesmo diretório. Runtime conferido no container: Python 3.12.12, FastAPI 0.141.1, Starlette 1.3.1, SQLAlchemy 2.0.43, asyncpg 0.30.0, Redis client 6.4.0 e HTTPX 0.28.1. A imagem exata está em run.json.image_id.

Máquina local com Docker Desktop; outras stacks estavam ativas durante a medição. A janela de carga foi exclusiva, sem parar serviços alheios. São medições locais curtas, não capacidade máxima ou SLO mensal.

O gerador usa taxa de chegada constante e sem retry; oferta nominal pode diferir por uma chegada em cada cenário na fronteira. Contadores fecham todas as conclusões e categorias. Warm-up de 5 s fica separado, inclusive após escalar para 1 ou 2 réplicas. Normal/ERP: 10/s por 15 s; retorno: 10/s por 10 s; quota: 60/s por 10 s; isolamento: A 60/s + B 5/s por 10 s. VUs fixos: 16 na mistura,20 no cliente quente e 4 no normal. Critérios mantidos: zero drop, conteúdo incorreto ou erro inesperado; p95/p99 de sucesso abaixo de 500/1500 ms, também nas rotas comerciais.

| Cenário | Oferta nominal | Iniciadas/concluídas | 200 corretas | 429 | 503/504 previstas | Drops | p50 sucesso ms | p95 sucesso ms | p99 sucesso ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| mixed-normal | 150 | 151/151 | 151 | 0 | 0 | 0 | 7.06 | 21.24 | 40.92 |
| mixed-erp-degraded | 150 | 151/151 | 114 | 0 | 37 | 0 | 6.69 | 11.17 | 19.10 |
| mixed-recovered | 100 | 101/101 | 101 | 0 | 0 | 0 | 6.92 | 10.68 | 19.52 |
| quota-one | 600 | 601/601 | 300 | 301 | 0 | 0 | 6.01 | 53.44 | 81.98 |
| quota-two | 600 | 601/601 | 300 | 301 | 0 | 0 | 6.00 | 9.25 | 32.79 |
| tenant-isolation | 650 | 652/652 | 351 | 301 | 0 | 0 | 6.17 | 18.08 | 48.89 |
| traces-down | 100 | 100/100 | 100 | 0 | 0 | 0 | 6.59 | 8.28 | 9.36 |
| pool-pressure | 200 | 201/201 | 0 | 0 | 201 | 0 | - | - | - |

Sob ERP degradado, as 37 falhas eram ERP; as 114 consultas comerciais (57 por tenant) foram corretas. A população de sucesso global muda, portanto não se interpreta seu p95 menor como melhoria. p95 por rota comparável:

| Rota | Normal ms | ERP degradado ms | Recuperado ms |
|---|---:|---:|---:|
| Resumo |13,04|18,24|17,01|
| Vendas |29,59|8,67|9,47|
| Lojas |24,09|8,47|9,89|

Cada série é curta; variação de cauda não mostra ganho causal. No isolamento, A concluiu 300 corretas/301 por quota e B 51/51 corretas. As duas configurações de quota admitiram 300 corretas em 10 s; adicionar réplica não duplicou a quota. Com admissão de autenticação 4, a carga de quota tinha tido duas respostas 503; o [diagnóstico](problem-solution.md) descreve o ajuste para 8 e a hipótese de cold-start descartada.

As latências de erro ficam separadas: ERP degradado p95/p99 de 906,47/907,30 ms; quota de uma réplica 7,55/38,37 ms; quota de duas réplicas 4,82/19,88 ms; isolamento 5,42/15,18 ms; pressão do banco997,56/1008,61 ms. Na pressão não houve resposta 200 durante a carga; portanto não existe p95 de sucesso para apresentar. Após liberar o lock, a receita conhecida de 27.877.248 voltou e checked-out do pool de dados chegou a zero.

Cache com quatro concorrentes por fase: 1/0/1 SQL. Somente cache indisponível permitiu cinco resultados corretos. Redis inteiro parado deu 503 quota_unavailable, live 200/ready 503 e zero SQL de resumo; recuperação foi conferida contra as linhas brutas do banco. O trickle individual terminou com 504 em 0,938 s, com resumo 200 independente e circuito aberto observado. Tracing desligado: 100 resultados corretos, RSS das APIs de 196.452.352 para 197.238.784 bytes; essa janela não demonstra ausência de crescimento por dias.

Alertas reais: perda de réplica entregue em 32,172 s e resolvida em 19,859 s depois da restauração; API inteira 30,062 s e 18,968 s. Uma ocorrência por ciclo; sete incidentes finais estavam resolvidos. [alerts-real.json](../artifacts/problem-review/20260921t064944662185z/alerts-real.json) contém tempos e targets novos após recriação. Logs/traces foram correlacionados depois do retorno.

resources-*.jsonl são snapshots Docker durante cada cenário; observations-*.json preserva amostras Prometheus a cada 5 s por réplica (admissão, pool, circuito, event-loop e RSS), e metrics-*.json guarda contadores antes/depois. Não são picos reais de CPU/memória nem quantis agregados por média.

## Medições anteriores

A matriz abaixo é histórica. O cenário atual usa mistura, verificador e limiares próprios; as medições antigas não foram executadas novamente.

Medições locais em 21/09/2026 UTC (madrugada de 20–21/09 em São Paulo). Artefatos são resultados executados; os dados comerciais e ERP são sintéticos. Os números não representam benchmark de produção nem capacidade máxima do hardware.

## Ambiente e método

Máquina local com Docker Desktop; outras stacks estavam ativas durante a medição. Serviços de teste isolados também existiam em parte da janela. Essa interferência limita a comparação de caudas.

As matrizes de carga, banco, cache, falhas de dependências e recursos abaixo são medições históricas anteriores à atualização de dependências de 21/09. Usaram Docker Engine 29.7.2, Desktop 4.89 e Compose 5.5; Python 3.12.12, FastAPI 0.116.1, Starlette 0.47.3, SQLAlchemy 2.0.43, asyncpg 0.30.0, Redis client 6.4.0, HTTPX 0.28.1. PostgreSQL 17.6, Redis server 7.4.5, NGINX 1.28.0, Prometheus 3.5.0, Alertmanager 0.28.1, Grafana 12.1.1, Jaeger 1.71.0 e k6 1.2.3.

O runtime atual usa FastAPI 0.141.1 e Starlette 1.3.1, fixados no `uv.lock`. A matriz histórica não foi repetida integralmente nem atribuída automaticamente a essas versões. Os testes de regressão estão em [verification.md](verification.md) e as medições posteriores na seção de regressões abaixo; imagens e limites estão em `compose.yml`.

O k6 usa `constant-arrival-rate`, sem esperar a resposta anterior para oferecer a próxima chegada. O padrão pré-aloca oito VUs, máximo 24; pool pressionado pré-aloca 24. Guardas: até 90 req/s, até 60 s, zero drops, respostas previstas e p99 total abaixo de 3 s com aborto. A série de sucesso é separada das rejeições. Contagens podem incluir a chegada na fronteira inicial/final: por isso 400 nominais podem resultar em 401 completas. Os JSON mantêm `testRunDurationMs`, taxas realizadas e contadores exatos.

## Carga pelo proxy

| Cenário | req/s | Oferta nominal | Completas | 200 | 429 | 503 | Drops | p50 200 ms | p95 200 ms | p99 200 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SQL, uma réplica | 5 | 100 | 100 | 100 | 0 | 0 | 0 | 16,56 | 18,68 | 19,59 |
| Cache, uma réplica | 20 | 400 | 401 | 401 | 0 | 0 | 0 | 5,90 | 10,73 | 36,24 |
| Cache, duas réplicas | 20 | 400 | 401 | 401 | 0 | 0 | 0 | 6,63 | 8,49 | 11,05 |
| Quota, uma réplica | 60 | 1200 | 1201 | 600 | 601 | 0 | 0 | 5,71 | 19,70 | 63,62 |
| Quota, duas réplicas | 60 | 1200 | 1201 | 600 | 601 | 0 | 0 | 5,81 | 9,40 | 144,63 |
| Jaeger parado | 10 | 100 | 101 | 101 | 0 | 0 | 0 | 6,57 | 12,39 | 25,25 |
| Pool bloqueado e liberado | 20 | 200 | 201 | 7 | 0 | 194 | 0 | 591,91 | 821,11 | 832,85 |

Os primeiros cinco cenários duram 20 s; os dois últimos, 10 s. Fontes: `artifacts/load-table.md` (artefato histórico local, não versionado) e `artifacts/load-*.json`. `scripts/report.py` gera o gráfico e a tabela diretamente dos JSON. A baseline SQL usa acesso de cache temporariamente bloqueado por ACL; a comparação tem taxas distintas e não isola o efeito do cache como experimento causal rigoroso. A redução de SQL aparece no contador abaixo.

As duas execuções de quota mantiveram cerca de 30 respostas úteis/s, sem 503, com metade da oferta recusada por política comercial. A cauda p99 com duas réplicas piorou nessa execução; não dá para prometer melhoria linear. Na última repetição do pool, sete consultas concluíram após a liberação do lock e 194 foram rejeitadas; percentis de sucesso com apenas sete observações têm pouca força estatística. Chamar rejeição rápida de ganho de latência seria incorreto. A duração global desse cenário teve p50 491,01 ms, p95 1004,24 ms e p99 1016,05 ms.

## Banco, cache e concorrência

Há 21.730 itens, 10.800 pedidos comerciais, 60 dias e fixture separada. `EXPLAIN (ANALYZE, BUFFERS)` do resumo de janeiro/loja 1: 4,201 ms de execução; `Index Only Scan` no índice `ix_sales_tenant_store_sold_id`, 1.862 linhas, 0 heap fetches, 112 shared-hit blocks e zero shared-read blocks no agregado. O índice começa por tenant/loja, depois instante/id e cobre valores do resumo; dados já em cache do PostgreSQL tornam esse resultado favorável. Plano dessa medição em `measurement-baseline.json.explain`; `experiments.json.explain` guarda a repetição mais recente.

Quatro consultas concorrentes por fase, com duas réplicas: frio 1 SQL, quente 0, após TTL 1. O contador é específico ao SQL de resumo; autenticação e leitura da versão ainda consultam o banco. Snapshots por instância antes/depois estão em `experiments.json.cache`. Há lock Redis com token, TTL 2 s, espera de preenchimento 250 ms e fallback dentro da admissão.

No isolamento, tenant A ofereceu 60 req/s e tenant B 5 req/s por 20 s. O contador `normal_failures` de B permaneceu 0. Isso mostra esse caso local, não justiça global para qualquer mistura de carga.

Pressão controlada: ferramenta mantém lock exclusivo temporário em `sale_items`, cache desabilitado por ACL, 20 req/s por 10 s. A aquisição de conexão tem timeout de 200 ms; SQL expira em 800 ms. O dashboard mostrou ocupação de 4 conexões de negócio por réplica e espera elevada. Um bug de gauge na devolução simultânea foi corrigido e o cenário foi repetido: snapshot final correto com 0 conexões de negócio emprestadas e 8 ociosas, e 101 timeouts de aquisição de dados, zero de auth. Budget: 2 réplicas × (4 negócio + 2 auth) = 12 conexões; máximo PostgreSQL 40. Contadores e histogramas por réplica foram preservados em `experiments.json.pool_pressure`.

A primeira tentativa desse cenário usou oito VUs e perdeu seis chegadas: reprovada, preservada em `artifacts/load-pool-pressure-generator-limited.json` (artefato histórico local, não versionado). Foi repetida com 24 VUs pré-alocados, sem drops. A última repetição após correção do gauge gerou 201 conclusões, sendo 194/503 e 7/200; a liberação do lock coincidiu com o fim da janela. A execução reprovada não fundamenta conclusão de capacidade.

## Falhas de dependências e recuperação

| Experimento real | Resultado observado |
|---|---|
| Apenas ACL do cache retirada | Cinco resumos 200; quota permaneceu funcional; ACL restaurada |
| Redis inteiro parado | Negócio 503 `quota_unavailable`; live 200; consultas recuperaram após retorno |
| ERP envia pequenos trechos continuamente | 504 em 0,906 s; resumo 200; circuito abriu e retomou após restauração |
| Backend de traces parado | 101 consultas 200; zero drops; soma do RSS das APIs 200.310.784 bytes antes/depois |
| Credencial revogada | Oito chamadas anteriores observaram ambas as réplicas com 200; oito posteriores observaram ambas com 401 |
| SIGTERM durante ERP ativo | Quatro requests terminaram com 504 dentro de ~1 s, inclusive na réplica parada; shutdown em 1,250 s, sem OOM |

RSS estável em dez segundos e fila de exportação limitada não mostram estabilidade por dias. O primeiro teste do prazo ERP mediu também a tentativa IPv6 de `localhost` no Windows, acrescentando cerca de dois segundos; o cliente operacional passou a usar `127.0.0.1`, coerente com o bind do Compose, e o caso foi repetido. O comportamento do proxy foi medido separadamente pelos testes HTTP/k6.

No SIGTERM, Uvicorn 0.35 concluiu o shutdown e então reenviou o sinal; exit 143 é registrado como está, não convertido em exit 0. Esse comportamento se repetiu na medição posterior. As repetições antes/depois da atualização estão em `artifacts/graceful-before-dependency-update.json` (artefato histórico local, não versionado) e `artifacts/graceful-real.json` (artefato histórico local, não versionado); o tempo de 1,250 s da tabela pertence à implementação inicial, não à execução atual.

## Alertas e investigação

`artifacts/alerts-real.json` (artefato histórico local, não versionado) registra a repetição após a atualização FastAPI/Starlette, com duas injeções reais, tempos monotônicos, objetos firing/resolved e deduplicação. O roteiro valida recuperação de todas as ocorrências novas e scrape posterior à recriação. O receiver continua persistindo quando todas as APIs estão paradas. A demo exige entrega e recuperação em até 90 s cada; janelas, scrape e agrupamento explicam a demora. A antiga inibição local foi retirada após suprimir uma entrega de recuperação; o registro anterior a essa retirada está em `artifacts/alerts-before-inhibition-fix.json` (artefato histórico local, não versionado).

| Falha final | Até entrega firing | Da restauração até entrega resolved | Ocorrências |
|---|---:|---:|---:|
| Uma réplica parada | 29,125 s | 19,782 s | 1 |
| Todas as APIs paradas | 34,953 s | 18,843 s | 1 |

O dashboard provisionado foi consultado com dados reais; a consulta pelo datasource Grafana retornou duas réplicas em `artifacts/grafana-datasource.json` (artefato histórico local, não versionado). O Jaeger exibiu o trace ERP `2d9ca6f8e5c4dfc907f5a784aae5ccd1` de 906,57 ms durante o encerramento. Seus spans HTTPX terminam nos headers; a espera do corpo estava no span de entrada. A versão final acrescenta `erp.availability` para cobrir corpo, validação e retries explicitamente.

`artifacts/trace-correlation.json` (artefato histórico local, não versionado) associa um request real, log JSON e spans SQL/Redis/HTTP pelo mesmo trace_id e request_id. O coletor exporta somente campos permitidos, sem tokens, headers ou texto SQL. Para reproduzir: `python scripts/trace_evidence.py`; depois abra o ID no Jaeger. SQL rápido com pool lento exige consultar também o histograma de aquisição de conexão; um trace sozinho não identifica toda espera anterior.

## Regressões após a atualização de segurança

FastAPI 0.141.1/Starlette 1.3.1: smoke k6 de 10 req/s por 10 s concluiu 101 consultas200, zero drops ou rejeições; p50 8,57 ms, p95 29,64 ms, p99 38,88 ms. Resultado em `artifacts/load-review-framework-update.json` (artefato histórico local, não versionado). A carga curta verifica o caminho atualizado, sem demonstrar equivalência de desempenho com toda a matriz histórica.

SIGTERM foi repetido: quatro requestsERP terminaram com 504 esperado, stop em 1,234 s, exit143 e sem OOM, em `artifacts/graceful-real.json` (artefato histórico local, não versionado). A medição anterior foi preservada em `artifacts/graceful-before-dependency-update.json` (artefato histórico local, não versionado). A coleta atual de trace apresenta seis spans e um log correlacionado. Testes HTTP, tipos e regras constam em [verification.md](verification.md).

## Recursos

Snapshot pós-experimentos, não picos, preservado em `measurement-baseline.json.resources`: API1 76,80 MiB; API2 77,21; PostgreSQL 59,09; Redis 3,83; proxy 2,28; ERP 36,86; receiver 44,10; Prometheus 58,00; Alertmanager 31,40; Grafana 103,00; Jaeger 16,55. Total aproximado 509 MiB. CPU instantânea: APIs 26,49% e 7,33%; demais serviços abaixo de 2%. Esses percentuais Docker são amostras, não percentis de toda a execução.

Limites da stack com duas APIs somam aproximadamente 2,05 GiB; gerador e ferramentas são temporários e têm limites adicionais. Dados de banco, alertas e TSDB ficam em volumes Docker; logs têm rotação. Prometheus retém até dois dias/256 MB. O custo operacional completo exige medir disco, CPU e memória numa janela maior antes de adaptar a produção.
