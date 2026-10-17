# Verificação

As provas publicadas incluem o [recibo completo](evidence/editorial-20260922/full-run.json), o [XML isolado](evidence/editorial-20260922/full-tests.xml), o [XML HTTP](evidence/editorial-20260922/full-http-tests.xml) e o [scan](evidence/editorial-20260922/full-vulnerabilities.json), de **22/09/2026**. Seus resultados valem para as versões executadas; a presença de um teste ou workflow no código não aprova edições posteriores.

Para entender o produto, comece pela [consulta de R$ 125,00, falha e recuperação](operational-story.md). Cada pacote abaixo preserva a versão executada. Para produzir evidência da sua cópia, execute `python scripts/review.py`; a saída aponta o novo `run.json`.

## Verificar a versão atual

### Checks de Python sem containers

Com Python 3.12 e uv, na raiz do projeto:

```sh
python -m uv sync --frozen
python -m uv run pytest tests/unit -q
python -m uv run ruff check .
python -m uv run ruff format --check .
python -m uv run mypy
```

`tzdata` faz parte do lockfile para que `America/Sao_Paulo` funcione também sem
uma base IANA instalada no sistema, conforme a [documentação de
zoneinfo](https://docs.python.org/3/library/zoneinfo.html#data-sources).
O teste `test_timezone_runtime.py` força essa condição em um processo separado.
As integrações PostgreSQL/Redis e os testes pelo proxy continuam exigindo o
ambiente descartável do runner. No Windows, os testes de permissões POSIX ficam
reservados ao Linux.

### Rodada completa no Linux de 12/10/2026

`python scripts/review.py --scenario all` passou no [CI 38204283171](https://github.com/arthurjoanes/api-sentinel/actions/runs/38204283171), no snapshot `bf7131886c38afe9991e35539e0f330651e435f3`. A execução `20261012t043755793312z` ocorreu de 01:37:55 a 01:47:20 em São Paulo. O [resumo publicado](evidence/evolution-20261012/summary.json) e o [recibo operacional](evidence/evolution-20261012/operational-run.json) identificam comandos, imagens, resultados e limpeza. Este incremento documental publica essa prova; mudanças posteriores exigem sua própria verificação.

| Gate | Resultado desta rodada |
| --- | --- |
| Build, Ruff, formato, mypy e monitoramento | Aprovados com o lock da versão executada. |
| PostgreSQL/Redis isolados | 361 casos e 15 subtests aprovados; 77 skips. [XML](evidence/evolution-20261012/tests.xml). |
| HTTP pelo proxy | 73 aprovados, sem skips. [XML](evidence/evolution-20261012/http-tests.xml). |
| Controles da ferramenta | 16 aprovados na imagem com o grupo `contracts`, incluindo servidor inválido, orçamento, prazo e replay. |
| Contratos gerados | 156 chamadas, 128 respostas 200 validadas e nenhum 500 inesperado. [Relatório](evidence/evolution-20261012/contracts-http.json). |
| Quota, carga e falhas | Políticas com uma/duas réplicas, carga mista, isolamento, cache, dependências, revogação e alertas aprovados. [Comparação limitada](performance.md#resultado-de-12102026). |
| Limpeza | Zero containers, volumes ou redes dos projetos da tentativa após o encerramento registrado. |

Os 77 skips isolados são 73 casos HTTP e quatro que exigem o grupo opcional `contracts`; foram executados nas etapas próprias. Os nove testes OpenAPI pertencem aos 361 casos isolados. Os 16 controles da ferramenta incluem casos também executados na suíte normal; essas contagens não são somadas como testes independentes. Os 25 testes locais descritos abaixo reuniram 16 controles e nove testes OpenAPI.

O contrato enviou 155 casos comerciais e uma leitura do OpenAPI: 120 gerados pelo schema, nove de autenticação, oito de domínio, nove de isolamento, sete positivos e dois de quota. Respostas negativas não preencheram a cobertura positiva.

| Operação | Casos comerciais | HTTP 200 validados |
| --- | ---: | ---: |
| `/v1/stores` | 36 | 32 |
| `/v1/stores/{store_id}/summary` | 40 | 33 |
| `/v1/stores/{store_id}/sales` | 42 | 32 |
| `/v1/stores/{store_id}/availability/{sku}` | 37 | 31 |

A fixture original foi conferida antes/depois e terminou com 12.500 centavos, dois pedidos e ticket de 6.250. A seed e seu manifesto descrevem a massa original; o provisionamento de contratos acrescentou seis linhas copiadas no banco descartável, três em cada loja 8/9, sem alterar as lojas originais. O [oráculo](evidence/evolution-20261012/oracle.json) e o recibo conservam essas identidades.

Os 160 hashes de fontes coincidiram antes/depois; HEAD permaneceu em `bf71318`, com árvore e diff vazios. O inventário dos 66 pacotes do runtime ficou idêntico e sem Schemathesis. As imagens de runtime `sha256:45d249e9…`, proxy `sha256:7129ec54…` e contratos `sha256:9095d437…` têm IDs completos no recibo. Os [scans da aplicação e do proxy](security.md#scan-de-12102026) preservam seu escopo.

Ubuntu 24.04 hospedado pelo GitHub: quatro CPUs e `memory_bytes=16765378560`. O inventário não tinha containers ou volumes antes da rodada nem após a limpeza; restaram somente as mesmas três redes nativas do Docker. IDs e labels dos recursos removidos estão registrados. Não havia containers alheios para testar preservação sob concorrência. Esse ambiente é distinto da tentativa Windows abaixo.

### Falha após reduzir as réplicas

A [execução 38206127094 do PR](https://github.com/arthurjoanes/api-sentinel/actions/runs/38206127094), no snapshot de merge `062a08b` da branch `e79190b`, falhou em `warmup-one` após reduzir duas réplicas para uma. Das 50 chamadas concluídas, 48 foram válidas e duas retornaram `503 proxy_unavailable`, sem drops. O [recibo da tentativa](evidence/evolution-20261012/failed-scale-preparation.json) conserva fontes estáveis, falha e limpeza dos recursos exclusivos. Seleção de peer removido ou DNS ainda antigo é uma inferência; os logs disponíveis não demonstram a causa no proxy.

A preparação agora confere IDs, labels de projeto/serviço e hostnames atuais; espera 3,25 s para a renovação DNS e exige uma janela contínua de três segundos de respostas 200, cobrindo todas as réplicas esperadas. O resultado fica em `run.json.scale_preparation`. Taxas, durações de carga e thresholds originais foram mantidos. A aprovação da correção depende de uma rodada própria, identificada pelo commit e pelos artefatos do CI.

### Rodada local de 12/10/2026

O [recibo local](evidence/evolution-20261012/local.json) identifica HEAD, alterações locais e hashes antes/depois. As fontes permaneceram estáveis. Ruff, formato e mypy passaram; a suíte com grupo `contracts` e regressões OpenAPI passou 25 testes, incluindo HTTP inválido, replay sanitizado, orçamento esgotado, JSON escalar e headers lentos. O comando sem Schemathesis retornou `failed` e exit 1, conforme o [controle de dependência ausente](evidence/evolution-20261012/missing-tool.json).

A suíte normal no Windows passou 317 casos e 15 subtests, com sete skips previstos para leitores Linux e testes que exigem o grupo `contracts`. Um teste existente falhou ao exigir modo POSIX `0600`: o Windows reportou `0666`. O código e o teste desse arquivo não foram alterados. Esse resultado local não aprova o gate Linux isolado.

Monitoramento e `python scripts/review.py --scenario all` foram tentados, mas o Docker Desktop não iniciou. A falha ocorreu antes de build ou criação de recursos da tentativa, ao acessar `sailor-ingest.sock`; o runner também registrou que não conseguiu conferir a limpeza. Renomear o socket falhou, o reinício nativo não concluiu e a revisão automática de aprovação rejeitou sua remoção. Nenhum reset ou prune foi executado. A rodada Linux acima tem recibo e ambiente próprios; sua aprovação não demonstra a recuperação do Docker local.

```sh
python scripts/review.py --scenario all
```

O runner executa build, Ruff check/format, mypy, monitoramento, PostgreSQL/Redis isolados, HTTP pelo proxy, contratos HTTP, carga e falhas. O gate de contratos é uma etapa própria também nos cenários `load` e `alerts`; `all` acrescenta a comparação limitada de quota. A aprovação depende dos resultados daquela rodada, incluindo limpeza e fontes estáveis. As provas de 22/09 abaixo conservam o escopo histórico.

Todas as chamadas Compose recebem `-p` exclusivo. A tentativa identifica tags e IDs da API, proxy e imagem de contratos; `SENTINEL_TEST_IMAGE` aponta para sua imagem de API. Banco, seed, credenciais e volumes são descartáveis. O registro conserva inventário anterior/posterior, IDs/labels, comandos, início/fim, HEAD, diff e hashes antes/depois. Fontes alteradas durante a rodada invalidam a associação dos resultados. Builds, scans e carga pesada executam em sequência; concorrência no host continua sendo uma condição ambiental a registrar.

### Gate de contratos HTTP

Schemathesis 4.30.1 pertence ao grupo não padrão `contracts`, com resolução no [lock](../uv.lock). A imagem `contracts` é construída pelo [Dockerfile próprio](../deploy/contracts/Dockerfile) a partir da imagem identificada da tentativa. O inventário de pacotes verifica que o runtime normal conserva suas dependências. Ferramenta ou dependência ausente reprova a etapa dedicada.

O runner prepara `/secrets/contracts.json` e executa este comando no serviço `contracts`, substituindo a identidade pelo projeto registrado:

```sh
python scripts/verify_contracts.py --base-url http://proxy --attempt "<projeto-do-run.json>" --credentials-file /secrets/contracts.json --report /artifacts/contracts-http.json --seed 20261012 --examples-per-operation 30 --rate 5 --max-cases 180 --deadline 90
```

No host, `uv run --group contracts python scripts/verify_contracts.py` usa os mesmos argumentos, com a URL loopback do proxy da tentativa e o caminho privado das credenciais. A identidade e a URL precisam corresponder à execução autorizada. Destino externo arbitrário é recusado.

Os padrões são até 30 exemplos por operação, cinco chamadas/s, no máximo 180 chamadas e prazo total de 90 s, com cada pedido limitado a três segundos. O limite total inclui os casos adicionais de cobertura; o relatório registra o consumo real. Orçamento ou prazo esgotado produz `incomplete`, sem apresentar a cobertura parcial como aprovação. `failed` identifica divergência ou falha do gate; `passed` exige todos os critérios.

O supervisor inclui importação, geração, HTTP e validação no prazo total. Se encerrar o worker antes do relatório final, informa `incomplete` e `partial_results_unavailable`; as contagens dessa tentativa ficam indisponíveis. Um resumo vazio nesse caso não comprova ausência de chamadas.

O resumo informa operação, cobertura 200, positivos/negativos, seed, política de quota e motivo de falha. HTTP 401/403/404/429 não conta como cobertura positiva. O cenário saudável e o caso dedicado de 429 usam tenants distintos, mantendo o limitador ativo. Período, cobertura, SKU, cursor de outra versão, autenticação e acesso entre tenants têm negativos explícitos, conforme o [contrato](data-contract.md#contrato-http-executável).

Para reproduzir a primeira falha, dentro da mesma ferramenta e contexto privado:

```sh
python scripts/verify_contracts.py --base-url http://proxy --attempt "<projeto-do-run.json>" --credentials-file /secrets/contracts.json --replay-report /artifacts/contracts-http.json --replay-case 0 --report /artifacts/contracts-replay.json
```

O índice seleciona um caso de `failures`; a autenticação vem do arquivo privado. O relatório conserva parâmetros e comando seguro, sem Authorization, cookies ou token na URL. A suíte da ferramenta inclui orçamento esgotado e servidor de controle que viola o schema; esse controle precisa ser rejeitado. Nenhum check de resposta é desligado genericamente para aprovar a geração.

### Gate de quota

A integração Redis verifica propriedades com sequências conhecidas: capacidade inicial e recuperação, taxa derivada da organização, TTL, clientes concorrentes, tenant independente, fronteira da janela, taxas menor/maior, estado corrompido, indisponibilidade e ACL. O [contrato de quota](architecture.md#políticas-de-quota) define os resultados 429/503 e a convenção de capacidade.

A comparação pelo proxy usa janela fixa e GCRA com uma e duas réplicas, inputs iguais e a imagem identificada. O runner confere política única antes da carga e rejeita configuração mista. Entre políticas, o runner interrompe o gerador, atualiza ambas as réplicas, confere configuração/TTL, aguarda o estado anterior e retoma. Os contadores, retries e custo observado ficam separados por rodada; os [limites da comparação](performance.md#comparar-janela-fixa-e-gcra) impedem atribuir throughput superior ou capacidade máxima a esse ensaio curto.

O scan mantém o gate HIGH/CRITICAL da aplicação e do proxy, além de Gitleaks no conteúdo publicável e histórico. Um novo relatório só aprova a imagem e as fontes que ele identifica; as evidências históricas não substituem esses gates.

### Contrato da central de incidentes

A [central de incidentes](incident-console.md) documenta a leitura manual, os totais retidos sem filtro, os inícios em sete dias UTC na amostra de até 100 registros filtrados e a separação entre período de origem e recebimento. Metadados e origem dos eventos aparecem por expansão. [Testes do resumo](../tests/unit/test_visual_summary.py), [do período](../tests/unit/test_incident_visual.py), [da leitura transacional](../tests/unit/test_receiver_storage_snapshot.py) e [da navegação](../tests/unit/test_receiver_ui.py) verificam esses contratos.

O [workflow](../.github/workflows/ci.yml) publica os XMLs das suítes isolada e HTTP nos artefatos de cada execução. A aprovação pertence ao SHA e aos resultados daquele run; a presença dos testes no código não aprova alterações posteriores.

## Execução editorial completa — 22/09 às 12:12 UTC

Executei `python scripts/review.py --scenario all --keep` em banco, rede e volumes novos. A base foi `452509b`, com alterações locais no runner/coletor identificadas pelos hashes das fontes. A [prova desta rodada](evidence/editorial-20260922/full-run.json) está aprovada; não herda o resultado do CI de outro commit.

- Build pelo Dockerfile e lock atuais, Ruff, formatação, mypy e regras de monitoramento: aprovados.
- **261 testes e 11 subtests** isolados aprovados. Os 73 casos HTTP reservados nessa etapa foram executados depois: **73 aprovados, sem skips**. [XML isolado](evidence/editorial-20260922/full-tests.xml) · [XML HTTP](evidence/editorial-20260922/full-http-tests.xml).
- Consulta de referência antes/depois: **12500 centavos, 2 pedidos e 6250 centavos de ticket**, com cobertura completa. [Oráculo independente](evidence/editorial-20260922/full-oracle.json).
- Carga normal, ERP lento e recuperado; quota com uma/duas réplicas; isolamento; Redis indisponível; pressão no banco; revogação: critérios originais aprovados. [Contadores e limites](performance.md).
- Dois ciclos reais de alerta, mesma ocorrência recuperada, correlação e duas réplicas coletadas no final. [Entregas e tempos](evidence/editorial-20260922/full-alerts.json).
- Trivy 0.74.0 na imagem exata, com pacotes de sistema, Python e binário Rust: **nenhum achado reportado**, sem arquivo de exclusões. [Relatório de escopo limitado](evidence/editorial-20260922/full-vulnerabilities.json).
- Limpeza do namespace descartável concluída; nenhum container desse projeto restante. Os registros históricos foram preservados.

O coletor de imagens desta tentativa falhou ao tentar ler a credencial de uma réplica no instante em que o ensaio a parou. O [registro da falha](evidence/editorial-20260922/capture-attempt-01.json) fica separado da prova funcional aprovada. A correção seleciona outra réplica própria em execução e oferece uma espera opcional pelo registro da referência antes de injetar a primeira falha. Ela não interrompe a detecção ou a recuperação para fotografar.

A varredura de imagem não cobre todos os serviços auxiliares nem garante ausência de vulnerabilidades desconhecidas. A carga ocorreu sem outra stack Docker ativa no início e com janela reservada. A repetição para imagens não é uma nova medição de desempenho.

## Capturas do caso principal e instalação repetida — 22/09 às 12:49 UTC

Executei `python scripts/review.py --scenario alerts --keep --wait-for-capture`, com o coletor em outro processo. A [prova final](evidence/editorial-20260922/capture-run.json) identifica a base `452509b`, as mudanças locais, a imagem `sha256:2846db49…` e os hashes de todas as fontes operacionais. Build, Ruff, formato, mypy, monitoramento, **261 testes isolados + 11 subtests** e **73 testes HTTP** passaram. Os 73 skips da primeira etapa são justamente os casos HTTP executados depois, sem skips.

Foram obtidas três telas completas e dois recortes nativos: referência de R$ 125,00, ocorrência #2 ativa e recuperação recebida na mesma identidade. Fontes carregadas, zoom normal, nenhum erro de página e nenhuma alteração de DOM ou webhook artificial. A [história comentada](operational-story.md) mostra o que conferir; a [conta independente](evidence/editorial-20260922/capture-oracle.json) e os [eventos reais](evidence/editorial-20260922/capture-alerts.json) sustentam os resultados.

A imagem final recebeu [Trivy 0.74.0](evidence/editorial-20260922/capture-vulnerabilities.json), sem exclusões ou filtro de severidade: zero achados reportados em sistema, Python e binário Rust. A limpeza terminou sem containers, volumes ou redes desse projeto. Nenhum benchmark foi repetido nessa variante; as medições completas permanecem vinculadas à imagem das 12:12 UTC.

O [índice de tentativas](evidence/editorial-20260922/attempts.json) conserva as falhas: leitura da réplica parada; timeout de 3 segundos no Grafana; HTTP 503 durante a falha controlada; e uma linha do novo handshake reprovada por tamanho no lint. O timeout ocorreu com outras tarefas locais ativas, mas sua causa não foi demonstrada. Os critérios não foram relaxados; a rodada final passou com os mesmos testes.

## Qual prova responde a cada pergunta

| Pergunta                                                       | Versão ou identidade                                                                                                    | Evidência e limite                                                                                                                                                                                                                                                         |
| -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Qual execução completa foi registrada em 22/09 às 12:12 UTC?    | `20260922t121258511380z`, base `452509b` mais mudanças locais | [Prova completa desta rodada](evidence/editorial-20260922/full-run.json), com testes, carga, falhas, scan e limpeza; falha de captura registrada separadamente. |
| Qual execução sustenta as capturas de 22/09 às 12:49 UTC?       | `20260922t124941299601z`, mesma base e handshake identificado por hash | [Prova de capturas](evidence/editorial-20260922/capture-run.json), com nova instalação, testes e scan da imagem final; sem novo benchmark. |
| Qual foi a prova operacional de 22/09 às 02:19 UTC?             | Execução `20260922t021943129883z`, imagem `sha256:011252…`; identidade completa no JSON | [Prova operacional](evidence/publication.json), descrita abaixo. Inclui carga local e falhas reais, com massa/ERP sintéticos. |
| Qual foi o ciclo de alertas de 22/09 às 05:42 UTC?              | Execução histórica `20260922t054206130821z`, imagem `sha256:94dcc1…`, 113 fontes identificadas por hash | [Histórico da sequência](operational-story.md#histórico--execução-das-0542-utc) e [prova](evidence/operational-story-20260922/20260922t054206130821z/proof.json). Fixture conferida antes/depois e mesma ocorrência recuperada; sem novo benchmark ou scan naquela rodada. |
| Qual é o contrato atual da central?                            | Snapshot de incidentes retidos e amostra limitada do filtro selecionado | [Central de incidentes](incident-console.md) e testes de resumo, período e leitura transacional citados acima. Os gráficos não são métricas de disponibilidade. |
| O CI publicou resultados para um commit?                       | Cada execução de CI identifica o SHA e seus próprios artefatos | [Workflow](../.github/workflows/ci.yml), com XMLs das suítes isolada e HTTP e relatórios dos gates. Alteração local posterior não herda a aprovação desse commit. |

Uma fonte pode estar identificada por commit ou por um manifesto de hashes quando a execução usou um snapshot ainda não commitado. O registro precisa dizer qual caso se aplica. Quantidades de testes, subtests, requisições de carga e jornadas de navegador têm denominadores diferentes; não são somadas para formar um único indicador de qualidade.

## Interface durante incidente real — 22/09 às 05:42 UTC

O cenário limitado `alerts` aprovou build, lint, formato, tipos, regras de monitoramento, 257 testes isolados com 11 subtests e 73 testes HTTP. Os casos HTTP estavam reservados na primeira etapa e não são contados duas vezes. A fixture retornou R$ 125,00 em dois pedidos antes e depois; foram executados ciclos de perda de réplica e indisponibilidade das duas réplicas. A ocorrência fotografada manteve sua identidade ao receber a recuperação real.

As [três capturas comentadas](operational-story.md), [XMLs e hashes](evidence/operational-story-20260922/20260922t054206130821z/proof.json) permitem conferir o resultado. Os 113 arquivos operacionais coincidiram com o repositório na comparação posterior registrada; o snapshot não é apresentado como commit publicado. A limpeza removeu somente seu projeto descartável. O [histórico das tentativas](evidence/operational-story-20260922/index.json) conserva a falha de preparação da fixture e a prova do snapshot anterior.

## Prova operacional completa de 22/09/2026

Execução **20260922t021943129883z**, iniciada em 2026-09-22T02:19:43.130383+00:00 e concluída em 2026-09-22T02:29:00.260436+00:00: **aprovada**, incluindo recuperação e limpeza dos projetos temporários. Foi usada uma cópia das fontes de publicação; `.git`, caches e credenciais de execução ficaram fora do contexto Docker. As fontes operacionais e os sete runbooks ficaram inalterados durante a prova. Os arquivos de texto usam LF e seus bytes foram conferidos contra os filtros de publicação do Git, preservando os binários.

O [registro público](evidence/publication.json) contém a imagem exata, a impressão digital das fontes, os contadores de carga e o resultado de cada etapa. Os dados comerciais e o ERP são sintéticos; HTTP, PostgreSQL, Redis, proxy, entrega de alertas e traces foram executados em serviços locais reais.

| Verificação                 | Resultado                                                                                                                                                                      |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Build, Ruff, formato e mypy | Aprovados; dependências instaladas com lock congelado                                                                                                                          |
| Testes isolados             | 253 casos aprovados no XML, incluindo subtests, em 9,30 s; 73 testes HTTP reservados para a etapa seguinte                                                                     |
| Testes HTTP pelo proxy      | 73 aprovados em 17,52 s, sem skips                                                                                                                                             |
| Monitoramento               | Configurações Prometheus/Alertmanager e séries sintéticas de regras aprovadas                                                                                                  |
| Contrato da carga           | Respostas financeiras verificadas contra cálculo independente por linhas SQL, incluindo mutações inválidas do contrato                                                         |
| Cache                       | Quatro chamadas concorrentes por fase: SQL de resumo 1.0/0.0/1.0 em frio/quente/expirado                                                                                       |
| Quota e isolamento          | Taxas e critérios preservados com uma e duas réplicas; contadores completos em [desempenho](performance.md)                                                                    |
| Dependências e pressão      | Redis, ERP, backend de traces e bloqueio do banco exercitados, com respostas previstas e recuperação                                                                           |
| Autenticação                | Revogação entre réplicas, escopos e organizações verificados; cancelamento e reutilização dos pools data/auth testados com PostgreSQL real                                     |
| Controles de acesso         | Em volumes novos: Redis sem acesso anônimo e com ACL separada; Grafana Viewer sem administração ou login por senha. Usuários e sessões de volumes antigos não foram examinados |
| Estado final                | 2 réplicas coletadas, 0 incidentes ativos e fixture financeira conferida                                                                                                       |

A suíte isolada e a suíte HTTP estão separadas para não contar o mesmo teste duas vezes. Testes ASGI, relógios controlados, MockTransport e séries Prometheus verificam contratos determinísticos; os cenários de banco, proxy, carga e alertas usam processos reais. A prova testa alertas firing/resolved, descoberta após recriação, correlação de logs/traces e encerramento gracioso.

## Correções verificadas nesta publicação

A autenticação faz um único SELECT atual por requisição. Seu pool usa AUTOCOMMIT, preservando duas conexões, pre_ping, admissão 8 e os prazos originais. Isso remove quatro comandos BEGIN/ROLLBACK por consulta, sem criar cache de credenciais. Os testes verificam ausência de transação ociosa, reconexão após término do backend e cancelamento de SQL seguido de reutilização do pool.

A imagem pré-compila a biblioteca padrão e as dependências Python. O runtime permanece sem escrita de bytecode. O healthcheck periódico usa o wget já fornecido pelo BusyBox, preservando o GET de /health/live, o intervalo de 5 s, o prazo de leitura de 2 s e o timeout Docker de 3 s. Assim, a verificação não inicializa um interpretador Python dentro do mesmo limite de CPU da API. Foram verificados sucesso HTTP 200 e falha em HTTP 500, porta fechada e servidor sem resposta. As credenciais Redis são geradas em volumes exclusivos e preservadas ao repetir a inicialização; o usuário default fica desabilitado.

O protobuf 6.33.6 é compilado a partir do sdist fixado no lock para usar a implementação nativa upb no Alpine. O build verifica essa implementação após remover as ferramentas de compilação. A exportação de traces permanece ativa, com amostragem de 25%.

As tentativas anteriores que falharam em quota foram mantidas e resumidas no registro público. AUTOCOMMIT e bytecode pré-compilado não passaram sozinhos no ensaio completo. Um controle temporário sem traces motivou a investigação do custo de tracing, mas não é a configuração aprovada. A aprovação corresponde à execução completa identificada acima, com upb nativo, coleta de CPU sem iniciar Python no cgroup da API e todos os gates originais. A falha canônica anterior não foi reproduzida nesta execução; sua causa inicial continua não demonstrada.

## Segurança e reprodução

O [scan da imagem medida](evidence/runtime-vulnerabilities.json) foi feito com Trivy 0.74.0, sem exclusões de vulnerabilidades. O archive exportado está ligado ao identificador imutável da imagem executada; o SHA-256 de sua configuração foi verificado contra o identificador informado pelo scanner. O registro preserva os dois identificadores, pois manifest e configuração são objetos distintos no formato OCI. O gate bloqueia HIGH/CRITICAL; o registro informa todas as severidades encontradas. Esse scan cobre a imagem Python da aplicação, incluindo pacotes do sistema e bibliotecas, e não representa uma varredura de todas as imagens auxiliares. Os controles e limites estão em [segurança](security.md).

Para repetir a prova completa:

```sh
python scripts/review.py
```

O runner constrói a imagem e grava logs, XMLs, métricas, CPU por cgroup, oráculo e cargas em `artifacts/problem-review/<UTC>/`. Ele cria namespaces próprios, preserva a demonstração principal e encerra os recursos descartáveis inclusive em caso de falha. Reserve uma janela sem outras cargas pesadas no Docker. O [roteiro operacional](demo.md) explica as variantes e a inspeção com `--keep`.

## Escopo

São testes curtos de uma demonstração local, com duas réplicas no mesmo host. Não medem capacidade máxima, SLO de 30 dias, alta disponibilidade entre máquinas ou implantação pública com TLS e identidade corporativa. Dados e ERP são sintéticos; os resultados financeiros e os comportamentos locais descritos acima foram verificados.

A [execução histórica de 21/09 às 06:49 UTC](../artifacts/problem-review/20260921t064944662185z/summary.json) permanece versionada para consulta. Seus números e sua imagem pertencem àquela etapa, e não substituem a prova atual.

As páginas anteriores foram preservadas integralmente em [verificação antes desta publicação](verification-pre-publication-20260922.md) e [desempenho antes desta publicação](performance-pre-publication-20260922.md). Elas mantêm os estados pendentes e as conclusões das respectivas datas, incluindo a tentativa HTTP reduzida com erros de preparação. A [regressão independente de segurança](evidence/remediation-regression.json) conserva sua identidade, contagens e limites; seus casos não são somados novamente aos desta execução.
