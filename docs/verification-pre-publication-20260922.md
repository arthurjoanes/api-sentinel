# Testes executados

## Regressão de segurança em 22/09/2026 UTC — publicação ainda pendente

Uma cópia isolada dos 238 arquivos públicos foi comparada ao estado atual e testada sem alterar a demonstração ou o repositório original. O [registro dessa revisão](evidence/remediation-regression.json) contém identidade, hashes e contagens. A imagem `sha256:314f9f9f39a8384b32ad68d8921bd1cf67021bfe638218a678dceb0ee1d8aad1` já existia: 114 arquivos presentes em `/app` coincidiram byte a byte com a cópia; não houve novo build. Os 27 módulos pré-compilados corresponderam à compilação de seus fontes, e Protobuf 6.33.6 confirmou backend nativo `upb`.

- Passaram 242 testes e 11 subtests na suíte isolada, com PostgreSQL e Redis reais. Seus 73 testes HTTP ficaram explicitamente ignorados nesse comando. O XML contabiliza 253 casos aprovados incluindo os subtests.
- Os 73 HTTP passaram separadamente, em 17,92 segundos, pelo proxy com duas réplicas e os serviços de observabilidade da configuração documentada. Incluem os três testes de Grafana; não se somam esses três novamente.
- Ruff, formato de 69 arquivos, mypy em 27 fontes e os 47 casos sintéticos de monitoramento passaram. Promtool/amtool validaram os dois perfis.
- Redis recusou acesso anônimo/default, administração e cruzamento de chaves pelos usuários da aplicação. Grafana manteve dashboard anônimo somente leitura, recusou credencial administrativa pública e manteve login por senha desabilitado. Foram usados volumes novos; usuários e sessões de volumes antigos não foram examinados nem apagados.
- O scan já existente da mesma imagem foi conferido pelo hash do JSON e vínculo de identidade registrado: zero achados na imagem da aplicação. Isso não constitui uma nova varredura nem cobre as imagens auxiliares.

A primeira tentativa HTTP usou uma stack reduzida, sem receiver/observabilidade, e foi preservada: 16 casos passaram e 57 tiveram erro de preparação porque o helper observava somente uma das duas réplicas. A sequência alternada de health e fixture coincidia com o round-robin; consultas consecutivas à fixture confirmaram ambas com 200. A repetição usou a configuração documentada completa e passou sem alterar fontes, gates ou quantidade esperada de réplicas. Essa falha de preparação não foi classificada como erro de negócio nem atribuída à CPU.

Esta regressão **não substitui a prova operacional final pendente**. A execução canônica `20260922t010740342553z` falhou em quota-one: 574 conclusões, 38 recusas de capacidade, 12 outros erros e 27 drops. A execução release anterior `20260922t005657571493z` passou; a diferença e a falha posterior continuam preservadas. A correlação com atividade elevada no host não comprova causalidade. A publicação exige concluir a validação operacional com os gates originais, registrar o resultado e então atualizar as conclusões de desempenho.

Todos os recursos desta regressão, nos namespaces `fix-api-remediation-tests` e `fix-api-remediation-grafana`, foram removidos. As medições abaixo mantêm suas versões e datas históricas; não são automaticamente atribuídas a esta imagem.

## Execução histórica de 21/09/2026, 06:49 UTC

Execução [20260921t064944662185z](../artifacts/problem-review/20260921t064944662185z/run.json), de 06:49:44 a 06:57:51 UTC em 21/09/2026: aprovada, inclusive limpeza. Imagem e hashes das fontes constam no registro. Fontes operacionais ficaram inalteradas durante a medição. A massa é sintética; HTTP, PostgreSQL, Redis, proxy e entrega de alertas são reais locais.

- Ruff e formato: 64 arquivos; mypy: 27 fontes. Build com lock congelado.
- 229 testes isolados e nove subtestes em 9,84 s. Os 70 HTTP ignorados nessa suíte passaram separadamente pelo proxy em 15,08 s; não são contados duas vezes.
- 47 casos Prometheus: 26 demo, 13 referência, quatro de entrega e quatro de frescor. Promtool/amtool validaram as configurações; as séries desses testes são sintéticas.
- Treze verificações do contrato da carga, incluindo mutações de respostas 200 incorretas. Três guardas operacionais recusaram projeto inválido, saída fora de artifacts e injeção na demo.
- Carga, dependências, quota, pressão, revogação nas duas réplicas, alerta e recuperação passaram. [Resumo](../artifacts/problem-review/20260921t064944662185z/summary.json), [tabela](../artifacts/problem-review/20260921t064944662185z/load-table.md) e [método/limites](performance.md).

| Critério | Resultado executado |
|---|---|
| Mistura normal → ERP degradado → recuperação | 151/151 corretas; 114 comerciais corretas +37 falhas esperadas exclusivamente ERP; 101/101 corretas após retorno |
| Quota e isolamento | 300 corretas +301 quota em 601 conclusões, tanto em 1 como 2 réplicas; A: 300 corretas + 301 por quota; B: 51/51 corretas no isolamento |
| Cache e Redis | Quatro chamadas/fase: SQL 1/0/1. Redis inteiro parado: 503 quota_unavailable, live 200, ready 503 e zero SQL de resumo; volta ao total correto |
| Banco pressionado | 201/201 recusas 503 previstas, sem drop; não houve amostra de sucesso nessa fase. Após liberação: receita de 27.877.248 centavos e zero conexões de dados emprestadas |
| Traces parados | 100/100 resumos corretos, zero drops; RSS aumentou 786.432 bytes nessa janela, sem alegação de estabilidade longa |
| Alertas | Réplica: firing 32,172 s/resolved 19,859 s; API inteira: 30,062 s/18,968 s. Mesma ocorrência por ciclo; sete incidentes finais resolvidos |
| Estado final | Duas réplicas coletadas após recriação, fixture 12.500/2/6.250, trace/log correlacionados; 81 arquivos examinados sem tokens/segredos conhecidos da execução |

Duas execuções anteriores, com admissão de autenticação 4, tiveram duas recusas 503 no estágio auth durante a carga de quota, mesmo após aquecimento. A admissão passou de 4 para 8, mantendo pool 2 e prazos; a repetição manteve taxas e critérios. Isso é o resultado do caso local.

## Correção restrita após a medição

Havia uma lacuna no registro da limpeza: TimeoutExpired/OSError do subprocess poderiam ocorrer antes de registrar exit code. O estado agora fica cleanup_pending até terminar; exceção grava failed/cleanup_failure, horário final e preserva a falha original da medição. Três testes de regressão em Python no host passaram, cobrindo sucesso pendente, os dois erros de transporte e preservação da falha original. [Log](../artifacts/problem-review/cleanup-regression.log) e [hashes antes/depois](../artifacts/problem-review/cleanup-regression.json).

Somente scripts/review.py e seu novo teste mudaram depois da matriz; fontes da aplicação, contratos de carga e gates permaneceram idênticos. Não se atribui essa regressão à suíte completa nem se repete a carga sem necessidade. A imagem validada contém a aplicação medida; a próxima execução do runner construirá a versão com a guarda de limpeza.

Depois da conferência final, src/api_sentinel/queries.py mudou: coverage.complete passou a ser derivado dos limites de cobertura da loja em vez de True fixo. A matriz operacional e a suíte de testes não foram repetidas com essa versão; o hash atual do arquivo difere do registrado em run.json.

Conferência final em 07:16 UTC ([registro](../artifacts/problem-review/final-review.json)): a diferença de hashes corresponde à correção declarada; Ruff e formato passaram nos dois arquivos alterados, em container sem rede. A matriz operacional não foi repetida após essa alteração.

## Estado da demonstração principal

Em 07:02 UTC, APIs e receiver foram atualizados para a imagem validada, sem seed, reset ou migração ([refresh.json](../artifacts/problem-review/demo-refresh-20260921t070219z/refresh.json)). As APIs foram reconstruídas depois com a mudança de queries.py e não rodam mais essa imagem. A verificação daquele horário registrou autenticação 8, ready 200, dois targets up, fixture correta, zero incidentes ativos e quatro destinos 307 corretos. SHA de seis tabelas, incluindo 21.730 itens e credenciais, da configuração declarada/.env e de demo.json/cursor-key/webhook-token permaneceu idêntico. Os demais containers Sentinel conservaram seus IDs.

O primeiro verificador de refresh consultou a rota errada de incidentes e terminou com KeyError após a atualização. A correção repetiu somente leituras, sem novo restart. A comparação exata do histórico de incidentes antes/depois não foi feita porque a captura inicial era 404; o estado final contém 21 resolvidos. A comparação de dados/credenciais/segredos usou os snapshots válidos anteriores à atualização.

A navegação foi verificada por HTTP307 e HTML real ([central.html](../artifacts/problem-review/20260921t064944662185z/central.html)); não houve nova captura de navegador.

## Etapas anteriores

Para reproduzir com o código atual, use `python scripts/review.py` e [demo.md](demo.md). Os números abaixo pertencem às etapas identificadas.

Testes executados em 21/09/2026 UTC. Fontes, testes, documentação e arquivos gerados ficam no projeto; bancos e segredos ficam nos volumes Docker.

A implementação inicial aprovou 117 testes unitários/integração e 62 HTTP separadamente; a saída está em `final-tests.log`/`http-tests.xml`. Esses números e os benchmarks da matriz original precedem a atualização FastAPI/Starlette e não devem ser atribuídos automaticamente ao runtime atual.

A atualização da cadeia de dependências aprovou 165 testes isolados, com 65 HTTP explicitamente ignorados nessa suíte; os mesmos 65 passaram separadamente pelo proxy real em 15,06 s. `tests.xml`, `review-isolated-tests.log`, `review-http-tests.xml` e `review-http-tests.log` registram essa etapa. Ruff e formato passaram para 56 arquivos Python e mypy aprovou 26 fontes. Os 11 testes de UI/dashboard foram repetidos após ajustes de formato/nomenclatura e passaram; não são somados aos 165. Os avisos de depreciação Starlette TestClient/HTTPX e AnyIO foram preservados, sem falha funcional.

A etapa seguinte aprovou 221 testes isolados, 70 HTTP separadamente pelo proxy, 47 casos Prometheus, Ruff/formato e mypy. Ela corrigiu janela de retenção e contagem atômica, migração aditiva de atividade administrativa, frescor configurável, bordas de credencial/SKU/ID e apresentação operacional. Arquivos: `followup-tests.xml`, `followup-isolated-tests.log`, `followup-http-tests.xml`, `followup-http-tests.log` e `followup-monitoring-checks.log`. Às 04:51:03 UTC, `followup-final-state.json` registrou ready 200, duas réplicas coletadas, probe válido e aprovado, limite de frescor exportado, novas regras carregadas/saudáveis, zero incidentes ativos e nenhuma ocorrência dos tokens atuais nos arquivos públicos examinados.

O relatório pip-audit antes/depois está em `dependency-audit-before.json` e `dependency-audit-after.json`: sete IDs únicos corrigidos; 65 dependências publicadas consultadas, sem vulnerabilidades conhecidas no segundo relatório. O pacote local não está no catálogo PyPI e foi identificado como não auditável por essa ferramenta.

Cancelamento real na etapa histórica `cancel-db-tests.xml`: remoção da consulta ativa em cerca de 7,070 ms após disconnect e 6,720 ms após deadline; vida SQL total de 9,402/104,731 ms, inferior ao pg_sleep de 600 ms e ao statement_timeout de 800 ms. A regressão após o ajuste dos gauges (`db-pool-cancellation-tests.xml`) repetiu a aprovação com 5,296/6,527 ms de limpeza. Isso distingue cancelamento do simples término natural da consulta. A conexão foi reutilizada com SELECT 42; checked-out zero e nenhuma task residual.

## Resultados registrados

Executado real significa processo/serviço real no ambiente local. Simulado significa teste determinístico de contrato, ASGI, relógio ou série Prometheus; não é apresentado como falha externa observada.

| Critério crítico | Resultado | Natureza |
|---|---|---|
| Migração e setup repetíveis | `sentinel.ps1 setup -Replicas 2` executado novamente; manifesto status `preservado`, 21.730 itens, digest inalterado | Real PostgreSQL |
| Cálculo monetário, pedidos e datas | Fixture manual 12.500 centavos, dois pedidos, ticket 6.250; integração testa limites do dia São Paulo | Real PostgreSQL + exemplo independente |
| Tenant, escopo, expiração e cursores | Suíte security pelo proxy inclui IDs válidos de outro tenant, cache aquecido e cursores cruzados | Real HTTP/DB/Redis |
| Revogação nas duas réplicas | `experiments.json.revocation`: ambas 200 antes e ambas 401 depois | Real |
| Quota compartilhada | Mesmos 600 sucessos/601 recusas com uma e duas réplicas em 20 s a 60 req/s | Real k6/Redis |
| Admissão sem fila ilimitada | Entrada/auth/negócio/tenant têm limites imediatos; testes concorrentes e pressão de banco | ASGI simulado + real DB/k6 |
| SQL e índice | EXPLAIN ANALYZE: Index Only Scan, 1.862 linhas, zero heap fetches | Real massa sintética |
| Pools, espera e timeouts | Última pressão por lock:194 respostas503, 7 respostas 200 ao liberar o lock, zero drops; checked-out final zero | Real PostgreSQL |
| Cache frio/quente/expirado | Quatro chamadas concorrentes/fase geram 1/0/1 SQL de resumo | Real duas APIs/Redis |
| Cache isolado versus Redis inteiro | ACL cache: cinco 200; Redis parado: 503 quota_unavailable, live 200; retorno confirmado | Real |
| ERP independente e prazo total | Trickle real terminou 504 em 0,906 s; resumo 200; circuito abriu/recuperou | Real HTTP local |
| Contrato de ERP/SSRF | Destino fixo; sem redirects/proxy ambiente; schema, bytes e Content-Encoding rejeitados | Configuração + testes simulados e HTTP local |
| Cancelamento de SQL | Driver estava em pg_sleep antes do cancelamento; pool voltou a zero e conexão reutilizada | Real asyncpg/PostgreSQL |
| Cancelamento e limites ASGI | Disconnect, prazo, corpo/resposta, rota normalizada e ausência de tarefas pendentes | ASGI simulado |
| Encerramento gracioso | SIGTERM durante quatro requests; shutdown completo em 1,250 s, exit143, sem OOM | Real containers |
| Métricas e dashboard | Datasource Grafana→Prometheus retornou duas réplicas; UI mostrou tráfego, latência, erros e pools | Real HTTP + inspeção visual |
| Traces e logs correlacionados | `trace-correlation.json` liga request_id, trace_id, log e spans SQL/Redis/ERP | Real |
| Backend de traces indisponível | 101 respostas 200, zero drops em 10 s; RSS antes/depois igual nessa janela | Real |
| Probe independente | Tenant próprio, fixture, validação de status/schema/totais; NaN/config_valid quando configuração ausente | Real + contrato simulado |
| Regras e ruído | promtool: 43 casos demo/referência; saudável/pico/persistência/recuperação/ausência/baixo tráfego/reset/réplica/coleta/entrega | Séries sintéticas |
| Entrega firing/resolved | Parada de uma e de todas as APIs, receiver persiste e mantém uma ocorrência/início | Real Prometheus→AM→receiver |
| Descoberta após recriação | IDs novos e scrapes posteriores à conclusão do recreate, sem socket Docker | Real |
| Receiver autenticado/durável | Webhook autenticado, tamanho/schema, persistência antes do 2xx, repetição e ordem tardia | SQLite real + webhook controlado |
| Runbooks e UI | Sete rotas de runbook retornaram200/CSP; central mostra histórico, impacto e recuperação | Real HTTP + navegador |
| CI Linux | Workflow em `.github/workflows/ci.yml` com os mesmos containers e checks locais | Preparado |

`check` executa Ruff, formato, mypy e `scripts/check_monitoring.py`. Este último valida configurações Prometheus/Alertmanager, regras e testes dos conjuntos demo e referência. Somente o conjunto `demo` estava ativo na stack.

## Correções encontradas ao executar

- A primeira execução HTTP começou antes da prontidão do proxy; as fixtures passaram a aguardar live/ready, fixture conhecida e duas instâncias, com timeout. A repetição passou. Repr de credenciais foi redigida para evitar exposição em falhas de pytest.
- O middleware inicial não garantia limpeza do downstream ASGI. Foi substituído por fluxo explícito que cancela e aguarda aplicação/watcher, limita bytes e evita enviar sucesso parcial.
- Escrita de cache com falha podia recalcular SQL já concluído; agora retorna o resultado calculado dentro da política de fallback.
- Bytes descomprimidos podiam crescer antes do limite; ERP/probe solicitam identity e recusam outras codificações.
- Configuração inválida do probe não é falha de negócio: fica sem observação, com NaN e alerta de telemetria. A UI distingue esse estado.
- O writer do seed substituía credenciais com permissões que impediam a leitura do probe. Agora preserva owner/grupo/mode existentes e usa temporário exclusivo; primeira criação privada 0600. O bootstrap torna os arquivos deliberadamente legíveis nos containers autorizados pelo volume, conforme contrato local.
- O wrapper PowerShell tratava `-e` do Docker como parâmetro comum de função; simplificado para encaminhar argumentos e propagar código de saída.
- O teste de recriação aceitava scrape antigo. Agora exige containers novos e coleta com timestamp posterior ao recreate.
- O gauge do pool era estimado antes de devolver a conexão; liberações simultâneas podiam deixá-lo incorreto. A versão final lê o pool após a devolução e tem regressão concorrente. Histogramas/contadores anteriores continuam úteis; gauges históricos não devem ser usados para inferir recuperação precisa.
- URLs longas no proxy recebem Problem JSON414; respostas401 incluem `WWW-Authenticate: Bearer`.
- O primeiro teste de pool teve seis drops do gerador; preservado como reprovado e repetido com 24 VUs. O primeiro cliente ERP usou localhost/IPv6 e incorporou atraso externo à API; repetido com 127.0.0.1.

## Limites e simulações

O sistema é um laboratório local: organizações, produtos, vendas e ERP foram gerados. MockTransport e cliente ASGI de teste validam contratos específicos; os testes reais de banco, proxy, carga e alerta são listados separadamente. O resumo pode cair quando PostgreSQL falha; o objetivo é rejeitar em prazo e recuperar, não eliminar indisponibilidade.

Não foram validados SLO de 30 dias, escala em hosts diferentes, alta disponibilidade do banco/Redis, rede hostil pública, TLS em produção, provedor OAuth, entrega externa nem testes prolongados de memória. Não há integração Azure executada. Limites de taxa e SLO são hipóteses ajustáveis; os testes locais curtos não medem capacidade máxima.

Grafana, central e Jaeger foram conferidos no navegador. Capturas em [screenshots](screenshots), incluindo o detalhe da reconciliação e a versão mobile. A correlação de trace e log está no arquivo gerado por `scripts/trace_evidence.py`.

A stack final deve permanecer com duas réplicas e probe válido; `status`, Grafana e a central permitem verificar o estado atual, que pode mudar após esta execução.

Auditoria final executada às 04:20:24 UTC: `artifacts/final-state.json` registra readiness 200, duas réplicas coletadas, zero incidentes ativos, contratos de borda 414/401 corretos e nenhuma ocorrência dos tokens atuais nos fontes/testes/docs/arquivos examinados. Na implementação inicial, a consulta a `pg_roles` e `role_table_grants` no PostgreSQL real confirmou `sentinel_app` sem superuser/create role/create DB e somente privilégio SELECT; papéis/permissões não foram alterados depois. `python scripts/final_audit.py` reproduz a parte HTTP/arquivos; `scripts/trace_evidence.py` espera a recuperação do ERP em ambas as réplicas antes de selecionar um trace amostrado.
