# Verificação

Índice documental conferido em **22/09/2026**. As provas publicadas incluem [recibo completo](evidence/editorial-20260922/full-run.json), [XML isolado](evidence/editorial-20260922/full-tests.xml), [XML HTTP](evidence/editorial-20260922/full-http-tests.xml) e [scan](evidence/editorial-20260922/full-vulnerabilities.json), todos de **22/09/2026**. A presença de um teste no código ou de um workflow não significa que a revisão atual foi executada.

Para entender o produto, comece pela [consulta de R$ 125,00, falha e recuperação](operational-story.md). Este documento aprofunda os resultados por execução: os pacotes abaixo são históricos e preservam suas próprias versões. Para produzir evidência da sua cópia, execute `python scripts/review.py`; a saída aponta o novo `run.json`.

## Auditoria do candidato — 22/09/2026

A narrativa anterior descrevia uma inspeção sobre `f9d1c52704c285d7961da4545a9dbae7ecc2ca7b`, com resultados locais e consultas ao CI. Seus registros completos não estão ligados a um pacote público verificável nesta seção. Por isso, na revisão documental de **22/09/2026**, as contagens, tempos, inventários e conclusões de contratação sustentados apenas por essa narrativa foram retirados da apresentação de resultados comprovados.

As execuções com JSON/XML publicados continuam identificadas nas seções seguintes. A [configuração do CI](../.github/workflows/ci.yml) define os checks; sua existência não atesta aprovação de um commit. Esta revisão de documentação não repetiu builds, scans, falhas ou testes da aplicação.

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
| Qual execução sustenta a revisão editorial atual?              | `20260922t121258511380z`, base `452509b` mais mudanças locais                                                           | [Prova completa desta rodada](evidence/editorial-20260922/full-run.json), com testes, carga, falhas, scan e limpeza; falha de captura registrada separadamente.                                                                                                            |
| Qual execução sustenta as novas capturas?                      | `20260922t124941299601z`, mesma base e handshake identificado por hash                                                  | [Prova de capturas](evidence/editorial-20260922/capture-run.json), com nova instalação, testes e scan da imagem final; sem novo benchmark.                                                                                                                                 |
| Qual foi a prova completa anterior à adaptação visual?         | Execução `20260922t021943129883z`, imagem `sha256:011252…`; identidade completa no JSON                                 | [Prova operacional](evidence/publication.json), descrita abaixo. Inclui carga local e falhas reais, com massa/ERP sintéticos; antecede a revisão visual.                                                                                                                   |
| Como era a prova visual anterior?                              | Execução histórica `20260922t054206130821z`, imagem `sha256:94dcc1…`, 113 fontes identificadas por hash                 | [Histórico da sequência](operational-story.md#histórico--execução-das-0542-utc) e [prova](evidence/operational-story-20260922/20260922t054206130821z/proof.json). Fixture conferida antes/depois e mesma ocorrência recuperada; sem novo benchmark ou scan naquela rodada. |
| Qual revisão visual tem checks próprios?                       | Registro de 22/09 às 05:36 UTC; base `b5f0eed`, imagem `pf-api-sentinel-triage:20260922` e hashes discriminados no JSON | [Revisão de navegação](evidence/interface-navigation.json) e [explicação dos checks](interface-validation.md). Capturas com ocorrências sintéticas; checks de pacote e scan não repetem o ensaio de carga nem aprovam edições posteriores.                                 |
| O CI publicou resultados para um commit?                       | Cada execução de CI identifica o SHA e seus próprios artefatos                                                          | [Workflow](../.github/workflows/ci.yml) e [histórico da correção de exportação](interface-validation.md#correção-da-exportação-junit-no-ci). Alteração local posterior não herda a aprovação desse commit.                                                                 |
| Uma pessoa conseguiu usar os procedimentos sem ajuda contínua? | Ainda não há sessão humana registrada                                                                                   | [Protocolo preparado](demo.md#exercício-com-outra-pessoa--preparado-ainda-não-realizado). Execução automatizada não substitui essa avaliação.                                                                                                                              |

Uma fonte pode estar identificada por commit ou por um manifesto de hashes quando a execução usou um snapshot ainda não commitado. O registro precisa dizer qual caso se aplica. Quantidades de testes, subtests, requisições de carga e jornadas de navegador têm denominadores diferentes; não são somadas para formar um único indicador de qualidade.

## Interface durante incidente real — 22/09 às 05:42 UTC

O cenário limitado `alerts` aprovou build, lint, formato, tipos, regras de monitoramento, 257 testes isolados com 11 subtests e 73 testes HTTP. Os casos HTTP estavam reservados na primeira etapa e não são contados duas vezes. A fixture retornou R$ 125,00 em dois pedidos antes e depois; foram executados ciclos de perda de réplica e indisponibilidade das duas réplicas. A ocorrência fotografada manteve sua identidade ao receber a recuperação real.

As [três capturas comentadas](operational-story.md), [XMLs e hashes](evidence/operational-story-20260922/20260922t054206130821z/proof.json) permitem conferir o resultado. Os 113 arquivos operacionais coincidiram com o repositório na comparação posterior registrada; o snapshot não é apresentado como commit publicado. A limpeza removeu somente seu projeto descartável. O [histórico das tentativas](evidence/operational-story-20260922/index.json) conserva a falha de preparação da fixture e a prova anterior à última edição visual.

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
