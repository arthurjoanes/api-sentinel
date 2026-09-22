# Verificação

Execução **20260922t021943129883z**, iniciada em 2026-09-22T02:19:43.130383+00:00 e concluída em 2026-09-22T02:29:00.260436+00:00: **aprovada**, incluindo recuperação e limpeza dos projetos temporários. Foi usada uma cópia das fontes de publicação; `.git`, caches e credenciais de execução ficaram fora do contexto Docker. As fontes operacionais e os sete runbooks ficaram inalterados durante a prova. Os arquivos de texto usam LF e seus bytes foram conferidos contra os filtros de publicação do Git, preservando os binários.

O [registro público](evidence/publication.json) contém a imagem exata, a impressão digital das fontes, os contadores de carga e o resultado de cada etapa. Os dados comerciais e o ERP são sintéticos; HTTP, PostgreSQL, Redis, proxy, entrega de alertas e traces foram executados em serviços locais reais.

| Verificação | Resultado |
|---|---|
| Build, Ruff, formato e mypy | Aprovados; dependências instaladas com lock congelado |
| Testes isolados | 253 casos aprovados no XML, incluindo subtests, em 9,30 s; 73 testes HTTP reservados para a etapa seguinte |
| Testes HTTP pelo proxy | 73 aprovados em 17,52 s, sem skips |
| Monitoramento | Configurações Prometheus/Alertmanager e séries sintéticas de regras aprovadas |
| Contrato da carga | Respostas financeiras verificadas contra cálculo independente por linhas SQL, incluindo mutações inválidas do contrato |
| Cache | Quatro chamadas concorrentes por fase: SQL de resumo 1.0/0.0/1.0 em frio/quente/expirado |
| Quota e isolamento | Taxas e critérios preservados com uma e duas réplicas; contadores completos em [desempenho](performance.md) |
| Dependências e pressão | Redis, ERP, backend de traces e bloqueio do banco exercitados, com respostas previstas e recuperação |
| Autenticação | Revogação entre réplicas, escopos e organizações verificados; cancelamento e reutilização dos pools data/auth testados com PostgreSQL real |
| Controles de acesso | Em volumes novos: Redis sem acesso anônimo e com ACL separada; Grafana Viewer sem administração ou login por senha. Usuários e sessões de volumes antigos não foram examinados |
| Estado final | 2 réplicas coletadas, 0 incidentes ativos e fixture financeira conferida |

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
