# Revisão de segurança do API Sentinel em 3 de outubro de 2026

A API mantém isolamento por organização e loja, consultas parametrizadas e tokens com expiração e revogação. Esta revisão acrescentou limites temporais antes da autenticação e do webhook. O uso previsto continua sendo uma demonstração em loopback, com dados sintéticos e controle do host pelo operador.

O checklist recebido contém 18 itens preenchidos; o item 19 está vazio. Os resultados abaixo distinguem controles verificados, correções e limitações desse ambiente.

## Resultado por item

| Item | Resultado | Evidência e limite |
| --- | --- | --- |
| 1 Arquivo env exposto | Controlado no escopo local | `.gitignore` e `.dockerignore` excluem `.env` e runtime; somente `.env.example` é rastreado. O proxy só encaminha rotas da aplicação. Gitleaks examinou 21 commits sem achados. |
| 2 Validação frontend | Adequado à interface de consulta | O receiver apresenta links e filtros; não há formulário comercial de escrita. Campos da URL continuam sendo validados pelo servidor; a interface não substitui esse controle. |
| 3 Validação backend | Controlado | `src/api_sentinel/app.py`, `queries.py` e `alert_receiver/contracts.py` validam lojas, datas, SKU, filtros e webhook antes das operações. |
| 4 SQL injection | Controlado | `auth.authenticate`, `queries` e `AlertStore` usam expressões SQLAlchemy ou placeholders SQLite. Valores recebidos não compõem SQL. Integrações reais conferem isolamento e filtros. |
| 5 Autenticação fraca | Controlado com ressalva local | Bearer de 32 bytes aleatórios, SHA-256 no banco, escopos e rejeição de cabeçalhos duplicados. As senhas PostgreSQL identificadas como locais permanecem públicas no Compose; são um pressuposto da demo, inadequado para implantação compartilhada. |
| 6 IDOR | Controlado | `auth.authorize` verifica loja e escopo antes de cache e ERP; consultas e cursor incluem tenant. `test_cross_tenant_and_scope_rejected_before_business_query` testa o limite com PostgreSQL real. A central de incidentes é uma página operacional local sem contas de usuários. |
| 7 Senhas em texto puro no banco | Sem cadastro de senhas humanas | A tabela `credentials` guarda hash do token, expiração e revogação. Segredos da CLI ficam em volume local. Isso não elimina as credenciais locais documentadas do banco. |
| 8 Força bruta | Corrigido | `principal` aplica limite por peer antes do banco: 100 requisições/s, rajada 200. O webhook aceita 10/s, rajada 20. Excesso retorna 429 e `Retry-After`; cabeçalhos encaminhados não mudam o peer. |
| 9 Bloqueio durante envio e duplicidade | Controlado | Consultas comerciais são GET. Preenchimento de cache usa lock com token; webhook persiste fingerprint e início sob transação e preserva histórico das repetições. O backend protege concorrência mesmo sem estado de botão. |
| 10 CSRF | Não se aplica à autenticação atual | Bearer explícito, sem cookie de sessão ou CORS liberado. A escrita do webhook exige seu Bearer e JSON. Não existe credencial ambiente de navegador que autorize uma escrita. |
| 11 Upload sem validação | Não se aplica | Não há endpoint de upload. O webhook tem contrato estrito, corpo de até 64 KiB e prazo total de leitura; a API comercial tem orçamento próprio. |
| 12 Informações em erros | Controlado | `RequestMiddleware` e handlers retornam problemas genéricos; logs omitem mensagens SQL, cabeçalhos e payloads. Testes verificam marcadores privados ausentes em resposta e log. |
| 13 Dependências vulneráveis | Corrigido na aplicação e no proxy auditados | pip-audit 2.10.1 consultou OSV para 66 dependências resolvidas do lock, incluindo ferramentas. Trivy examinou a aplicação e o proxy corrigido. O proxy original tinha dois HIGH, um MEDIUM e um UNKNOWN; os quatro pacotes foram atualizados e o scan final ficou sem achados. As demais imagens auxiliares e ferramentas de navegador têm escopo separado. |
| 14 Armazenamento expiração e validação de tokens | Controlado com ressalva local | `authenticate` consulta expiração e revogação a cada chamada; cursor tem HMAC e escopo. A seed emite tokens de demo por 365 dias. O bootstrap usa `0644` no volume compartilhado de segredos para os UIDs da demo; segregar volumes e reduzir validade é necessário antes de exposição compartilhada. |
| 15 Rate limit | Corrigido e controles existentes preservados | O novo limite de autenticação antecede a consulta do hash. Quota Redis por organização continua atômica e compartilhada; admissão limita trabalho em andamento. O webhook recebeu limite temporal próprio. |
| 16 Dados sensíveis expostos | Controlado no escopo local | Dados são sintéticos; respostas e logs não retornam tokens ou segredos. `/internal/` é bloqueado pelo proxy. Painéis e incidentes são legíveis em loopback pelo operador, sem isolamento entre contas na interface operacional. |
| 17 SSRF | Controlado | `ERP` usa destino configurado, SKU limitado e `follow_redirects=False`; o usuário não escolhe host. `tool_url` admite apenas ferramentas conhecidas e origens loopback configuradas; links de alertas não fornecem o destino. |
| 18 Cookies inseguros | Não se aplica à API e ao receiver | Não há cookie de autenticação nesses componentes. A configuração do Grafana tem Viewer anônimo e login por senha desativado; cookies de serviços auxiliares exigem revisão própria se forem expostos. |

## Correções e testes

O limitador em `src/api_sentinel/rate_limit.py` usa tempo monotônico e lock. Guarda até 1.024 peers e um orçamento de overflow; endereços novos não expulsam orçamentos ativos. O peer vem da conexão ASGI. O processo principal já desativa proxy headers. Esses limites são por processo e não substituem a quota Redis por tenant; clientes atrás do mesmo proxy compartilham o orçamento de peer.

Regressões verificam disputa concorrente por um orçamento, reposição, crescimento limitado de memória, recusa antes do banco e impossibilidade de contornar o limite com `X-Forwarded-For`. O teste do receiver confirma que excesso de tentativas não persiste incidentes nem bloqueia o healthcheck.

A execução final em Linux, com PostgreSQL e Redis descartáveis, passou 271 testes e 11 subtests, sem casos pulados: [JUnit](evidence/security-review-20261003/linux-tests.xml). Ruff, formatação e mypy passaram. A execução inicial teve uma corrida no teste de reconexão: `pg_terminate_backend` sem timeout só confirma o envio do sinal. O teste passou a esperar a saída real com timeout de 1.000 ms, conforme a [documentação PostgreSQL](https://www.postgresql.org/docs/17/functions-admin.html#FUNCTIONS-ADMIN-SIGNAL); a [primeira rodada](evidence/security-review-20261003/linux-first-tests.xml) permanece registrada. Testar permissões POSIX no Windows havia falhado; a execução Linux verificou os UIDs e permissões reais.

pip-audit consultou OSV sem achados conhecidos: [dependências Python](evidence/security-review-20261003/python-dependencies.json). A imagem `api-sentinel-security-review:20261003` foi construída a partir do Dockerfile e dos locks atuais, e o [scan Trivy](evidence/security-review-20261003/runtime-image-vulnerabilities.json) identifica seu digest e os pacotes examinados. Trivy 0.74.0 usou a base consultada em 03/10/2026; a ausência da data de fim de suporte do Alpine 3.24 na lista interna permanece como advertência. Gitleaks 8.30.1 passou no [histórico](evidence/security-review-20261003/secrets-history.json), com redação habilitada.

Trivy não encontrou vulnerabilidades na imagem da aplicação. Gitleaks também passou no [snapshot dos arquivos publicáveis atuais](evidence/security-review-20261003/secrets-current.json). Os dois achados iniciais eram o fingerprint público da chave de assinatura Python, presente nos metadados da imagem e no [Dockerfile oficial](https://github.com/docker-library/python/blob/master/3.13/alpine3.24/Dockerfile). A exceção exige aquele valor literal no caminho exato do relatório. Um [token fictício inserido nesse mesmo caminho](evidence/security-review-20261003/secrets-positive-control.json) continuou sendo detectado no controle positivo.

## Conferência complementar do CI

O gate HTTP de segurança e operações passou 73 testes em 17,51 s, pelo proxy com duas réplicas e observabilidade completa: [JUnit](evidence/security-continuation-20261003/http-tests.xml). A execução usou a imagem já auditada, banco e volumes novos, portas alternativas e namespace próprio; todos esses recursos foram removidos ao final. Nenhum teste precisou de alteração.

`scripts/check_monitoring.py` validou as configurações demo e referência e os 47 casos de séries sintéticas: [log](evidence/security-continuation-20261003/monitoring.log). A [conferência dos gates](evidence/security-continuation-20261003/ci-review.json) registra comandos e escopo. As referências locais da documentação foram verificadas sem faltas. Essa prova local cobre os gates indicados; a medição histórica de desempenho mantém seu resultado e sua data.

## Preparação para publicação

O relatório Trivy publicável mantém a identidade da imagem, o sistema operacional, os pacotes e os resultados da análise. Configuração de imagem, variáveis de ambiente e histórico de construção foram removidos dos metadados. Os testes e o scan continuam sendo as execuções registradas acima; essa redução não alterou a imagem nem seus resultados. Nos JUnit iniciais, os resultados e as falhas foram preservados; a preparação normalizou espaços finais do traceback Linux e redigiu prefixos do perfil do operador no traceback Windows. O [recibo de preparação](evidence/security-review-20261003/publication-preparation.json) registra os hashes e a conferência dos resultados preservados.

## Correção complementar do proxy

O [scan do proxy original](evidence/proxy-patch-20261003/original-proxy-vulnerabilities.json), em 03/10/2026, encontrou quatro ocorrências em 71 pacotes: `libexpat` e `pcre2` com severidade HIGH, `nghttp2-libs` com MEDIUM e `libpng` com UNKNOWN. A [receita do proxy](../deploy/proxy/Dockerfile) preserva a base Nginx 1.30.5 e seu digest, e atualiza apenas esses quatro pacotes para `2.8.5-r0`, `10.49-r0`, `1.70.0-r0` e `1.6.59-r0`, respectivamente. O [scan final completo](evidence/proxy-patch-20261003/final-proxy-vulnerabilities.json) ficou sem achados, com as versões instaladas verificadas e Nginx 1.30.5-r1 preservado.

As correções constam na [base de segurança Alpine 3.24](https://secdb.alpinelinux.org/v3.24/main.json) e nas fontes upstream: [Expat](https://github.com/libexpat/libexpat/blob/R_2_8_5/expat/Changes), [PCRE2](https://github.com/PCRE2Project/pcre2/security/advisories/GHSA-r9hj-j2rw-4q3m), [libpng](https://github.com/pnggroup/libpng/security/advisories/GHSA-qvg3-h654-xq3j) e [nghttp2](https://github.com/nghttp2/nghttp2/commit/ab28105c4a0197da24f8bfc414bc116055249e1e). A severidade UNKNOWN do libpng foi preservada como reportada por Trivy.

O Compose, o setup PowerShell e o runner operacional passam a construir essa receita. O CI examina a aplicação e o proxy, mantém o bloqueio integral de HIGH/CRITICAL e publica relatórios sem configuração de imagem ou variáveis de ambiente. Os ensaios locais usaram PostgreSQL, Redis, ERP, duas réplicas da API e proxy em um projeto descartável, com volumes novos e porta alternativa. A configuração Nginx foi validada; os [70 testes HTTP dirigidos](evidence/proxy-patch-20261003/proxy-http-tests.xml) passaram sem erros ou skips, conferindo prontidão, consultas autenticadas, isolamento, limites de entrada e identificação das duas réplicas. O [recibo](evidence/proxy-patch-20261003/verification.json) registra os resultados e a limpeza dos recursos.

A [primeira tentativa](evidence/proxy-patch-20261003/first-proxy-http-tests.xml) passou 13 casos e teve 57 erros de setup: a fixture alternava health e summary e observava sempre a mesma réplica com o round-robin de dois servidores. O [probe dirigido](evidence/proxy-patch-20261003/cadence-probe.json) confirmou uma réplica em 12 pares alternados e duas em 12 summaries consecutivos, todos com HTTP 200 e totais corretos. As duas fixtures agora verificam health quando necessário e consultam summaries consecutivos; preservam o prazo de 90 s, os totais exigidos e a expectativa de duas réplicas. O código da aplicação foi preservado.

Os pins dependem da disponibilidade dos pacotes nos índices Alpine; uma reconstrução futura deve conferir as versões e repetir o scan. Trivy também avisou que Alpine 3.24.2 não consta na sua lista interna de fim de suporte; esse aviso permanece no recibo e não certifica o ciclo de suporte do sistema. As demais imagens auxiliares continuam fora deste incremento.

## Revisão da prosa

O Humanizer 3.1.0 foi aplicado em modo de arquivo ao README, segurança, contrato de dados, problema e solução, e a este relatório. A revisão identificou rótulos em negrito, pontuação repetitiva e contrastes dispensáveis; reescreveu a prosa, conferiu os fatos e releu o resultado. Comandos, blocos de código, links, paths, números e artefatos históricos foram preservados. O [registro editorial](evidence/security-review-20261003/humanizer.json) informa o escopo e as verificações dos elementos protegidos.

## Limites da conclusão

Esta rodada verifica o código local e os controles descritos. Não executou carga de longa duração, teste de disponibilidade entre hosts ou ataque a uma implantação pública. Não substitui a política de identidade, TLS, segregação de segredos e scans das imagens auxiliares necessários para uma implantação compartilhada. Na rodada inicial, não houve commit ou push. A demonstração já em execução permaneceu intacta.
