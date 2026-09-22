# Desempenho e recuperação

Fontes numéricas conferidas em **22/09/2026**: [execução das 12:12 UTC](evidence/editorial-20260922/full-run.json) e [execução das 02:19 UTC](evidence/publication.json), ambas de **22/09/2026**. Taxas, contagens e percentis pertencem a seus cenários e não são extrapolados para produção.

## Execução de 22/09 às 12:12 UTC

Repeti a matriz completa em um projeto Docker novo, com as fontes identificadas na [prova atual](evidence/editorial-20260922/full-run.json). O tráfego usa lojas, vendas e ERP sintéticos; banco, Redis, proxy e requisições são reais. Os critérios não foram reduzidos para aprovar a rodada.

| Cenário                                        | Duração configurada | Iniciadas / concluídas | Respostas válidas | Recusas 429 | Falhas previstas do ERP |
| ---------------------------------------------- | ------------------: | ---------------------: | ----------------: | ----------: | ----------------------: |
| Mistura normal, 10 chegadas/s                  |                15 s |              151 / 151 |               151 |           0 |                       0 |
| ERP enviando o corpo aos poucos, 10 chegadas/s |                15 s |              151 / 151 |               114 |           0 |                      37 |
| Após recuperação do ERP, 10 chegadas/s         |                10 s |              100 / 100 |               100 |           0 |                       0 |
| Quota com uma réplica, 60 chegadas/s           |                10 s |              600 / 600 |               300 |         300 |                       0 |
| Quota com duas réplicas, 60 chegadas/s         |                10 s |              601 / 601 |               300 |         301 |                       0 |

Não houve iterações descartadas, respostas inválidas nem recusas de capacidade nesses cinco cenários. O gerador pode iniciar uma iteração na fronteira da duração; por isso a contagem observada não é substituída pela multiplicação nominal de taxa × segundos. As 114 respostas válidas e 37 falhas previstas do ERP são categorias diferentes, não uma taxa única de sucesso do produto.

No isolamento entre organizações, A teve 300 respostas válidas e 301 recusas de quota; B teve 51 válidas e nenhuma recusa. O cache gerou **1 / 0 / 1** consultas SQL nas fases fria, quente e expirada, com quatro chamadas por fase. Redis inteiro indisponível retornou 503 e **zero SQL adicional de resumo**; cache isoladamente indisponível respondeu às cinco consultas de controle. A pressão deliberada no banco produziu 201 recusas previstas, zero resultado inválido e recuperação do pool, sem apresentá-las como consultas bem-sucedidas.

Esses são ensaios curtos no mesmo host, não uma capacidade máxima ou um SLO mensal. A comparação registra resultados e denominadores completos; não atribuo redução de latência a uma troca de interface. Os tempos de alerta, no [registro próprio](evidence/editorial-20260922/full-alerts.json), também não representam tempo de resposta de uma pessoa.

## Medições anteriores preservadas

Medição local da execução **20260922t021943129883z**, na mesma imagem identificada em [publication.json](evidence/publication.json). Todos os cenários obrigatórios passaram. Runtime Python 3.12.14, FastAPI 0.141.1, Starlette 1.3.1, SQLAlchemy 2.0.43 e asyncpg 0.30.0; versões e limites estão fixados no projeto. Dados comerciais e ERP são sintéticos.

## Método

Método registrado em [publication.json](evidence/publication.json), execução de **22/09/2026, 02:19 UTC**; gerador e thresholds em [load](../load/review.js).

O k6 oferece chegadas em taxa constante, sem esperar a resposta anterior nem repetir requisições. Cada resposta 200 é conferida contra um oráculo independente, calculado a partir das linhas SQL. Warmup de 5 s fica separado, também após alterar o número de réplicas. A oferta na fronteira pode produzir uma chegada adicional; iniciadas, concluídas, categorias e drops são registrados integralmente.

Mistura normal e ERP degradado: 10 req/s por 15 s. Recuperação: 10 req/s por 10 s. Quota: 60 req/s por 10 s. Isolamento: cliente A a 60 req/s e B a 5 req/s por 10 s. A mistura usa 16 VUs; cliente quente usa 20 e cliente normal usa quatro, sem expansão durante o teste.

Critérios preservados: zero drops, conteúdo incorreto e resultados inesperados; p95/p99 das respostas corretas abaixo de 500/1500 ms, inclusive nas rotas comerciais; p99 global abaixo de 3 s com aborto. Rejeições por quota e erros previstos de ERP são contados separadamente.

| Cenário            | Oferta nominal | Iniciadas/concluídas | 200 corretas | 429 | Falhas previstas | Drops | p50 sucesso ms | p95 sucesso ms | p99 sucesso ms |
| ------------------ | -------------: | -------------------: | -----------: | --: | ---------------: | ----: | -------------: | -------------: | -------------: |
| mixed-normal       |            150 |              150/150 |          150 |   0 |                0 |     0 |           6,53 |           8,83 |          56,50 |
| mixed-erp-degraded |            150 |              151/151 |          114 |   0 |               37 |     0 |           6,52 |           8,22 |          17,29 |
| mixed-recovered    |            100 |              101/101 |          101 |   0 |                0 |     0 |           6,71 |           7,81 |          17,59 |
| quota-one          |            600 |              601/601 |          300 | 301 |                0 |     0 |           5,62 |           7,82 |           9,87 |
| quota-two          |            600 |              601/601 |          300 | 301 |                0 |     0 |           6,93 |          11,36 |          23,00 |
| tenant-isolation   |            650 |              652/652 |          351 | 301 |                0 |     0 |           7,34 |          11,13 |          17,63 |

As falhas previstas da mistura degradada pertencem ao ERP. Os demais caminhos comerciais precisam continuar corretos. As respostas 429 representam quota contratada, sem duplicação do limite ao passar de uma para duas réplicas. O registro público mantém também as categorias separadas por cliente e os thresholds de cada métrica; rejeições rápidas não são apresentadas como melhoria de latência das respostas úteis.

## Banco, cache e limites

Cada réplica tem quatro conexões de dados e duas de autenticação, sem overflow. Aquisição: 200 ms; autenticação total: 500 ms; SQL: 800 ms; prazo da requisição: 2 s. A admissão é imediata e limitada por entrada, autenticação, negócio e cliente. Duas réplicas somam até 12 conexões nesses pools, frente ao limite PostgreSQL de 40.

A autenticação consulta o estado atual a cada requisição e usa AUTOCOMMIT para o seu único SELECT. pre_ping e reconexão permanecem ativos. O cache evita repetir o cálculo financeiro; autenticação e versão do dataset ainda consultam o banco. Quatro chamadas concorrentes por fase produziram 1.0/0.0/1.0 consultas de resumo em frio/quente/expirado.

A pressão de banco usa lock temporário em sale_items e cache desabilitado por ACL. O teste exige recusa prevista em prazo, ausência de drops e recuperação com resultado financeiro correto e zero conexões de dados emprestadas. Os cenários também distinguem falha apenas do cache de indisponibilidade do Redis inteiro, que fecha a quota e retorna 503.

## CPU e tentativas anteriores

Fonte histórica: campos `runtime_optimization`, `bounded_quota_validation` e `earlier_attempts` de [publication.json](evidence/publication.json), **22/09/2026**. Esses microtestes e controles não foram repetidos nesta revisão.

As primeiras tentativas de publicação falharam na admissão de autenticação durante quota. O ensaio reduzido A/B mostrou que remover transações redundantes, sozinho, não bastava. Foi medido o custo de CPU da importação em um microteste: a importação fria de urllib.request pelo healthcheck consumia cerca de 0,67 CPU-s; após pré-compilar a stdlib, cerca de 0,09 CPU-s no mesmo microcontainer. O healthcheck compartilha o limite de 0,75 CPU da API. Esse microteste não identifica sozinho a causa das falhas de quota.

A pré-compilação não eliminou a falha de quota. O protobuf instalado a partir do wheel universal usava a implementação Python no Alpine. Em um microteste de serialização de 32 spans, a mediana de CPU foi 26,17 ms com Python e 4,57 ms com upb nativo. Dois controles temporários sem traces passaram; eles foram usados para diagnóstico, não como configuração de publicação.

A implementação nativa também não bastou sozinha: a primeira carga após iniciar uma API ainda podia falhar. Um controle separado com GOMAXPROCS=1 no k6 não resolveu o problema.

O healthcheck foi então trocado por wget do BusyBox, sem alterar endpoint ou prazos. Isso remove a inicialização periódica de Python do mesmo cgroup da API. O healthcheck também rejeitou HTTP 500, porta fechada e ausência de resposta no prazo. As 3 cargas delimitadas abaixo usaram processos de API recém-iniciados; as contagens vêm das rodadas reais em `bounded_quota_validation.rounds`, separadas da tabela da prova completa.

| Rodada de quota | Iniciadas/concluídas | 200 corretas | 429 | Resultados inesperados | Drops |
| --------------- | -------------------: | -----------: | --: | ---------------------: | ----: |
| 1               |              601/601 |          300 | 301 |                      0 |     0 |
| 2               |              600/600 |          300 | 300 |                      0 |     0 |
| 3               |              600/600 |          300 | 300 |                      0 |     0 |

A imagem final pré-compila stdlib, dependências e aplicação e constrói o mesmo protobuf 6.33.6 do lock com upb nativo. A exportação de traces e a amostragem de 25% permanecem ativas na prova aprovada.

A coleta de `cpu.stat`/`cpu.max`/`cpu.pressure` usa `cat`; iniciar Python dentro do cgroup medido distorcia o diagnóstico inicial. Nenhum limite de admissão, prazo, taxa ou threshold foi ampliado para aprovar esta execução.

Na tentativa canônica `20260922t010740342553z`, o k6 registrou 282 respostas válidas, 242 recusas por quota, 38 por capacidade, 12 outros erros e 27 drops. Os 12 outros erros foram 11 respostas `database_pool_busy` e uma `cache_fill_busy`. As métricas da API registraram rejeições nas admissões auth e tenant, timeouts nos pools auth e data e espera de preenchimento do cache expirada. Esses agregados também incluem tráfego além do k6; as 40 entradas de saturação no log da API não equivalem a 40 respostas de capacidade no gerador. Não se tratava somente das rejeições de autenticação das primeiras tentativas.

Essas correções e a aprovação atual não transformam a comparação inicial em um experimento causal completo. A falha canônica anterior não foi reproduzida nesta execução; sua causa inicial continua não demonstrada. Os logs reprovados foram preservados. A prova de 02:19 UTC e suas rodadas delimitadas de quota usaram a imagem histórica identificada nessa seção. A tabela de 12:12 UTC, no início desta página, pertence à nova execução `20260922t121258511380z` e à imagem registrada em seu próprio recibo; não é uma repetição com a imagem anterior.

## Limites da medição

Fonte: `docker_resources`, `measurement_conditions` e `bounded_quota_validation` no [recibo histórico](evidence/publication.json), **22/09/2026**.

Docker informado pelo runner: `CPUs=16 memory_bytes=16707645440 version=29.7.2`. As APIs, banco, gerador e observabilidade compartilham o host.

Antes da tentativa canônica reprovada, uma amostra externa registrou cerca de 3,12 CPUs lógicas em outros containers; as amostras Windows de 90–99% ocorreram depois do intervalo daquela quota. Essas observações não medem a carga efetiva do host durante a falha nem demonstram sua causa. Os recursos alheios foram preservados.

Na janela das três rodadas de quota, 32 amostras do host variaram entre 21% e 83% (2026-09-22T02:29:48.9861987Z a 2026-09-22T02:31:23.8783851Z); o host não era dedicado nem completamente ocioso. Esse intervalo pertence à validação delimitada, não à prova completa. O registro público identifica a imagem e o hash da série de amostras.

Os números descrevem as execuções identificadas, sem representar um benchmark em máquina exclusiva. As amostras Docker e Prometheus são observações pontuais; não representam picos contínuos nem percentis de CPU/memória. Estatísticas de poucos segundos não demonstram estabilidade prolongada.

Falhas de ERP, Redis, banco, traces e ciclos de alertas foram provocadas e recuperadas localmente. O resultado demonstra esses cenários e contratos; não mede capacidade máxima, benefício linear de réplicas, SLO mensal, disponibilidade entre hosts ou entrega externa. Os testes e o escopo da varredura estão em [verificação](verification.md).

O histórico integral permanece em [desempenho antes desta publicação](performance-pre-publication-20260922.md) e [verificação antes desta publicação](verification-pre-publication-20260922.md), com as ressalvas e falhas então registradas. A [regressão independente de segurança](evidence/remediation-regression.json) é uma evidência separada; suas contagens não são adicionadas às da prova completa.
