# Validação da interface — 22/09/2026

A revisão mais recente parte de `be419e0` e está em
[frontend-quality.md](frontend-quality.md), com matriz de 11 dimensões, capturas
comparáveis e prova de empacotamento separada. As seções abaixo descrevem rodadas
anteriores; suas imagens e hashes não são atribuídos ao candidato mais recente.

Limpeza posterior sobre `28261f9`: removida somente a variável CSS `--surface`, sem consumidores nos templates ou no JavaScript. O [registro separado](evidence/interface-css-cleanup-20260922.json) guarda hashes antes/depois e conferência de sintaxe. As imagens, capturas e manifestos anteriores permanecem históricos e não representam os bytes do CSS após essa remoção; não houve novo build ou ensaio visual.

## Triagem, navegação e documentação

Esta revisão parte de `b5f0eed`. A prova [interface-navigation.json](evidence/interface-navigation.json) identifica a imagem `pf-api-sentinel-triage:20260922`, arquivos empacotados, checks e capturas. `interface-review.json`, `interface-package.json` e a prova operacional permanecem históricos; seus hashes não representam os arquivos alterados nesta rodada.

A central usa navegação horizontal e uma lista linear: estado, impacto, momento relevante e investigação ficam visíveis; identificação e entregas abrem por expansão. Os filtros são uma barra compacta com contagens, sem aparência de indicadores de desempenho. A observação do probe permanece separada; no celular, um atalho permite chegar a ela sem atravessar a lista inteira. O detalhe coloca impacto e próximo passo antes de uma cronologia compacta. Encerramento manual tem indicação neutra; recuperação exige a entrega correspondente.

A revisão visual consultou exemplos oficiais de [Grafana Alert List](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/alert-list/), [Karma](https://github.com/prymitive/karma) e [cState](https://github.com/cstate/cstate), além de orientações de [hierarquia do Carbon](https://carbondesignsystem.com/data-visualization/dashboards/) e [detalhe sob demanda do NN/g](https://www.nngroup.com/articles/progressive-disclosure/). São referências de padrões, não aprovação por usuários do Sentinel. A implementação é original; não foram copiados código, estilos, textos ou assets. Não foram trazidos gráficos, silenciamento de alertas ou indicadores que o receiver não calcula.

Uma versão intermediária com filtros em cards e ocorrências altas adiava a triagem. A inspeção levou à barra compacta e à lista atual. Cabeçalho e conteúdo compartilham eixos centralizados, limitados a 1380 pixels. Títulos menores, corpo de leitura de 14 pixels e metadados subordinados reduzem a competição visual; cor acompanha texto de estado. Hover/foco têm transições de 180 ms, desativadas por movimento reduzido, sem simulação de atividade ao vivo.

## Comparação com o mesmo recorte

O renderizador e os assets de `b5f0eed` foram executados com os mesmos registros SQLite, títulos, horários, filtro Finalizados e probe desativado do candidato. Viewport de 900 pixels de altura; posições arredondadas em pixels CSS. O aviso sintético aparece nas duas versões.

| Largura | Início da primeira ocorrência: baseline → candidato | Linhas inteiras visíveis: baseline → candidato |
| ------- | --------------------------------------------------- | ---------------------------------------------- |
| 1440    | 504 → 383                                           | 2 → 2                                          |
| 768     | 498 → 374                                           | 2 → 2                                          |
| 390     | 778 → 462                                           | 0 → 2                                          |
| 320     | 817 → 462                                           | 0 → 1                                          |

A linha de desktop passou de cerca de 110 para 139 pixels: a ação explícita e a expansão ocupam espaço. A redução principal ocorre antes da lista, que começa mais cedo; não se afirma que todo elemento ficou menor. Em 1920 pixels o conteúdo mantém os eixos e o limite de largura. Essas medidas descrevem composição com duas ocorrências sintéticas; não medem produtividade ou preferência de operadores.

Comparações: [baseline 1440](screenshots/navigation-review/baseline-resolved-1440.png) / [candidato 1440](screenshots/navigation-review/candidate-resolved-1440.png), [baseline 768](screenshots/navigation-review/baseline-resolved-768.png) / [candidato 768](screenshots/navigation-review/candidate-resolved-768.png), [baseline 390](screenshots/navigation-review/baseline-resolved-390.png) / [candidato 390](screenshots/navigation-review/candidate-resolved-390.png), [baseline 320](screenshots/navigation-review/baseline-resolved-320.png) / [candidato 320](screenshots/navigation-review/candidate-resolved-320.png).

## Contratos e provas desta revisão

O baseline reproduziu três problemas funcionais: voltar do detalhe removia o filtro; o runbook não oferecia volta à ocorrência; investigação sem configuração abria JSON cru no navegador. A correção transporta somente filtro validado e ID numérico limitado. O retorno foca a ocorrência ou, se ela tiver saído do filtro, o conteúdo. Runbooks conservam a volta ao incidente e o foco nas seções. Erros de ferramentas oferecem HTML ao navegador; clientes JSON e redirects válidos mantêm o contrato.

“Finalizados” reúne recuperações recebidas e encerramentos administrativos. Estados persistidos, regras de deduplicação, entrega atrasada e caminho comercial da API não mudaram. README, problema/solução, decisões técnicas e arquitetura explicam entrada → resultado, código, testes, motivo e limite.

| Verificação                                     | Resultado e escopo                                                                                                                                                 |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Edge + Playwright, receiver/SQLite descartáveis | 12 jornadas: três filtros em 1440, 768, 390 e 320 pixels; detalhe → runbook → detalhe → lista mantém contexto e foco                                               |
| Estados e refluxo                               | 16 rotas/estados × 5 larguras (1440, 768, 640, 390, 320); sem rolagem horizontal da página ou erros JavaScript                                                     |
| Teclado e retorno                               | Skip link, âncoras dos procedimentos, retorno à linha e fallback quando a linha sai do filtro                                                                      |
| Semântica                                       | Manual diferente de recuperação; firing atrasado ignorado permanece no histórico; probe desativado neutro e resultado recente vencendo sem recarga                 |
| Composição e contraste                          | 40 combinações de oito rotas em 1920, 1440, 768, 390 e 320; eixos coincidentes e pares computados de texto/fundo sem falhas nos limiares examinados                |
| Imagem nova, sem bind de fontes                 | Ruff global; formato de 70 arquivos; mypy de 27 fontes; 166 testes e 2 subtests, com 2 avisos de depreciação existentes; 116 arquivos correspondentes ao workspace |
| HTTP em processo na imagem                      | 20 rotas: assets idênticos aos bytes empacotados, sete runbooks, contexto e erros 404/422/503                                                                      |
| Trivy 0.74.0                                    | Zero achados, incluindo zero HIGH/CRITICAL; mesma política do CI, sem exceções; identidade e resultados no JSON                                                    |

O pacote inclui também alterações concorrentes no fingerprint operacional e seu teste: a pasta `data/` passa a participar da identidade das fontes. O coletor `scripts/capture_operational_story.cjs` foi lido e teve a sintaxe Node conferida; as execuções reais foram feitas por uma coleta independente, identificada abaixo. Os 116 arquivos empacotados desta revisão foram novamente comparados ao workspace após a conclusão dessa coleta. A imagem da UI e as imagens operacionais mantêm provas separadas.

O scanner reutilizou a base de 22/09 às 02:00:05 UTC, válida até 23/09 às 02:00:05 UTC, com rede desativada, `--skip-db-update`, `--offline-scan` e `--ignorefile /dev/null`. O aviso de Alpine 3.24 fora da lista EOL não impediu a análise de pacotes Alpine, Python e Rust. Nenhuma carga ou stack operacional foi iniciada para esta revisão da UI.

Limites: 640/320 pixels conferem refluxo equivalente a 1280 pixels a 200%/400%; não houve zoom nativo ou leitor de tela. O contraste computado usa 4,5:1, ou 3:1 para texto grande, e não constitui auditoria WCAG completa. Destinos válidos de Grafana/Jaeger foram conferidos por HTTP de redirect; a configuração ausente foi testada no navegador. Não houve ensaio com usuários ou nova medição de SLO/desempenho.

Capturas sintéticas: [central](screenshots/navigation-review/central-desktop.png), [celular](screenshots/navigation-review/central-mobile.png), [recuperação](screenshots/navigation-review/recovered-detail.png), [manual](screenshots/navigation-review/manual-detail.png), [runbook com retorno](screenshots/navigation-review/runbook-context.png), [ferramenta indisponível](screenshots/navigation-review/tool-unavailable.png) e [procedimento em 320 pixels](screenshots/navigation-review/reflow-320.png). O aviso de prévia distingue esses registros da stack.

Relatórios e scripts locais ficam em `.runtime/ui-journey/`, ignorado pelo Git: `preview.py`, `review.cjs`, `compare.cjs`, `visual-audit.cjs`, `check_candidate.py`, `candidate-checks.json`, `build.log`, `trivy.json` e `browser-review.json`. O JSON versionado registra comandos, checks e hashes. Testes HTTP de contexto e contratos estão em `tests/unit/test_receiver.py` e `test_receiver_diagnostics.py`.

## Coleta operacional complementar, com identidade própria

A coleta independente [20260922t054206130821z](evidence/operational-story-20260922/20260922t054206130821z/proof.json) terminou aprovada às 05:46:13 UTC. Seu cenário `alerts` usa a imagem `sha256:94dcc15433c1927806cf2c108dca1ad82d44874d37bfe8f28e2d1fbf93d391a7`, distinta da imagem de triagem `sha256:7f88c2148a310679b0a0d989c4ce57ce3eadd7f1b9daf44cdbee1b55990c11ee`. O manifesto dessa coleta contém 113 arquivos de runtime correspondentes ao workspace na conferência final; o manifesto do pacote contém 116 arquivos, com escopo próprio.

As três capturas mostram [consulta de referência confirmada](screenshots/operational-story-20260922/20260922t054206130821z/01-fixture-validada.png), [indisponibilidade ativa](screenshots/operational-story-20260922/20260922t054206130821z/02-incidente-ativo.png) e [recuperação da mesma ocorrência](screenshots/operational-story-20260922/20260922t054206130821z/03-mesma-ocorrencia-recuperada.png). O incidente 3 recebeu duas entregas e foi recuperado por webhook `resolved`; não houve encerramento manual. A detecção levou 29,797 s e a recuperação 18,360 s nesse ciclo local. A suíte isolada registrou 257 casos aprovados, 11 subtests e 73 skips; os 73 testes HTTP passaram separadamente. São resultados dessa execução, sem extrapolação para SLO mensal ou capacidade.

A limpeza do namespace terminou às 05:47:49 UTC, sem containers, volumes ou redes remanescentes registrados. A [coleta anterior](evidence/operational-story-20260922/20260922t053056476675z/proof.json), com imagem `sha256:8514769c7f12b904429085a7103752d7b8737fbe1eb404a8105ece1bc2901095`, permanece histórica: estilos, renderizador e coletor diferem da revisão final. A [tentativa inicial que falhou](evidence/operational-story-20260922/attempt-01.json) também foi preservada. Os manifestos exatos e suas comparações em LF não substituem os hashes de execução registrados. Nenhuma dessas duas coletas executou carga de desempenho ou novo Trivy; o scan da imagem de triagem está na prova de empacotamento desta revisão.

## Gate de segredos dos manifestos

Gitleaks 8.30.1 encontrou hashes SHA-256 de quatro arquivos de autenticação/contrato como `generic-api-key` nos manifestos operacionais. Os valores foram comparados aos bytes dos arquivos correspondentes. A exceção em `.gitleaks.toml` exige `AND` entre um dos quatro caminhos completos enumerados — `source-files.json` e `source-files-lf.json` das execuções `20260922t053056476675z` e `20260922t054206130821z` — e um dos quatro valores exatos. Nenhum arquivo inteiro ou diretório foi excluído, e as regras padrão permanecem ativas.

O scan do snapshot completo de rastreados e novos não ignorados terminou sem achados. Vinte controles verificaram cada caminho: antes da exceção há quatro achados; caminho e hashes exatos não geram achados; outra execução, outro nome de arquivo ou outros valores continuam gerando quatro achados. Scripts e resultados locais: `.runtime/ui-journey/check_secrets.py`, `check_story_allowlist.py`, `gitleaks.json` e `gitleaks-story-controls.json`. As provas da coleta foram somente lidas por esta revisão; nenhuma credencial foi adicionada à allowlist.

## Primeira adaptação e empacotamento (histórico preservado)

Adaptação sobre o commit `d03e3c5`. O registro [interface-review.json](evidence/interface-review.json) identifica os arquivos da primeira rodada por SHA-256. Essa rodada cobre a central, seus estados, navegação e renderização. O registro complementar [interface-package.json](evidence/interface-package.json) verifica a nova imagem, sem atribuir a ela uma nova prova de carga.

## O que mudou

A central abre a lista de todas as ocorrências, com filtros, estado, impacto e última observação. A consulta de referência ocupa uma faixa compacta e continua vencendo na tela sem atualizar os dados. O detalhe apresenta impacto, condição, ação recomendada e cronologia; entregas repetidas, firing atrasado e encerramento administrativo permanecem distinguíveis.

Runbooks têm catálogo em `/runbooks`, navegação por seções, listas semânticas e código escapado. Os destinos de Grafana, Jaeger e Prometheus conservam a resolução das URLs da mesma execução. A central não consulta métricas, quotas por cliente ou targets para preencher indicadores.

## Verificações realizadas

| Verificação                                                          | Resultado                                                                                                                             |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Testes de UI, receiver, probe, retenção, erros, configuração e links | 134 testes e 9 subtests aprovados                                                                                                     |
| Ruff nos arquivos Python envolvidos e módulo receiver                | Aprovado; formato de 11 arquivos conferido                                                                                            |
| mypy no receiver                                                     | Aprovado; 8 arquivos de origem                                                                                                        |
| Edge headless com Playwright                                         | 12 telas/estados em 1440, 768, 640, 390 e 320 pixels de largura                                                                       |
| Refluxo de conteúdo                                                  | Nenhuma rolagem horizontal da página inteira nos 60 recortes                                                                          |
| Navegação e JavaScript                                               | Link para pular ao conteúdo é o primeiro foco; link da observação abre seus detalhes; resultado recente vence; nenhum erro JavaScript |
| Inspeção visual                                                      | Central desktop/celular, detalhe, catálogo e procedimento examinados                                                                  |

As larguras são pixels CSS. O recorte de 640 pixels confere a reorganização equivalente a uma janela de 1280 pixels com 200% de ampliação; não foi medido zoom nativo do navegador. Blocos de código podem rolar dentro do procedimento.

Os testes usam as dependências da imagem operacional aprovada, com as fontes desta adaptação montadas separadamente. Dois avisos de depreciação existentes em FastAPI/Starlette foram emitidos; não houve falhas. Nenhuma dependência ou framework de frontend foi adicionado.

## Capturas e reprodução

As capturas usam dados sintéticos explícitos, renderizados pelo código da aplicação, sem alterar o armazenamento da demonstração. O aviso de prévia aparece nas imagens. Os números de incidentes e horários dessas imagens não são medições operacionais.

- [Central desktop](screenshots/incidents-desktop.png) e [celular](screenshots/incidents-mobile.png).
- [Detalhe e histórico](screenshots/incident-history-desktop.png).
- [Catálogo de runbooks](screenshots/runbooks-desktop.png) e [procedimento](screenshots/runbook-desktop.png).

Em um ambiente com as dependências do projeto, na raiz:

```sh
python scripts/render_ui_preview.py
python -m http.server 9814 --bind 127.0.0.1 --directory .runtime/ui-preview
```

O gerador escreve 21 páginas estáticas em `.runtime/ui-preview`, incluindo resultado antigo, probe desativado, falha, ausência de ocorrências, erro de histórico, textos longos e encerramento manual. Ele não executa probe, webhook ou carga. As variantes `firing.html` e `resolved.html` são arquivos de revisão; os filtros por query string pertencem à aplicação real, testada via HTTP em processo. As ferramentas de investigação também dependem da aplicação real e de seus destinos configurados.

## Relação com a prova operacional

A prova [20260922t021943129883z](evidence/publication.json) permanece aprovada para a imagem `sha256:01125213503f621fac5a7f84389976266d83374aa793cbfd06350af43568d944` e fontes `d485c54b6fe01895def538c885e152799537fab6c01773052231a7c06997c0e9`. Ela terminou em 22/09/2026 às 02:29:00 UTC, antes desta adaptação. Os resultados de desempenho, recuperação e scan não foram renomeados nem atribuídos à nova interface.

A primeira rodada visual não incluiu build, ensaio de carga, entrega real de alertas ou scan. O build e a verificação complementar abaixo cobrem o empacotamento do candidato. As regras, os contratos de persistência e o caminho comercial da API permaneceram fora da mudança.

## Verificação complementar da imagem

A imagem `pf-api-sentinel-ui:20260922`, construída em 22/09/2026 às 03:27 UTC, foi examinada com os arquivos de `/app` que o Dockerfile copiou. Os containers de teste usaram rede desativada, sistema de arquivos somente leitura e `/tmp` temporário, sem montar fontes do workspace. O scanner teve acesso ao Docker e à rede para obter a base de vulnerabilidades.

| Verificação na imagem                                                | Resultado                                                                                            |
| -------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| Ruff global                                                          | Aprovado                                                                                             |
| Formato Python global                                                | 70 arquivos conferidos                                                                               |
| mypy nos alvos configurados pelo projeto                             | 27 arquivos aprovados                                                                                |
| Testes de receiver, UI, probe, retenção, configuração e investigação | 134 testes e 9 subtests aprovados; 2 avisos de depreciação existentes                                |
| Comparação de `/app` com o workspace                                 | 115 arquivos com SHA-256 correspondente; fontes da primeira rodada preservadas                       |
| Rotas HTTP em processo, com SQLite descartável e probe desativado    | Central, health, CSS, JavaScript, catálogo e 7 runbooks com HTTP 200; slug desconhecido com HTTP 404 |
| Assets HTTP                                                          | Conteúdo servido idêntico aos bytes de CSS e JavaScript copiados para a imagem                       |
| Trivy no candidato                                                   | Nenhum achado nos pacotes Alpine, Python e binário Rust `uv`; zero HIGH/CRITICAL                     |

O registro complementar guarda os hashes dos 115 arquivos, os comandos, os resultados das rotas e o relatório resumido do scan. Distingue o índice OCI retornado por `docker image inspect` (`sha256:e4d6e0387af362bab25c7ca1e36b6a3301832fc640841ec30b2da9767e4b0945`) do manifesto Linux/amd64 (`sha256:e2de71b6e1034c6ac3739fdf17d831e2f0e083908610159536d447a8bb37a88a`) e da identidade reportada pelo Trivy.

O scan terminou em 22/09/2026 às 03:53:47 UTC e usa a imagem Trivy 0.74.0 fixada pelo CI, scanner `vuln`, `--ignorefile /dev/null`, análise de pacotes do sistema e das linguagens e bloqueio para qualquer achado HIGH/CRITICAL. A base foi atualizada às 02:00:05 UTC do mesmo dia, com próxima atualização prevista para 23/09/2026 às 02:00:05 UTC. O resultado e a identidade da base estão em `checks.vulnerability_scan` no JSON complementar. O Trivy avisou que Alpine 3.24 não constava em sua lista de fim de suporte; a análise de vulnerabilidades dos pacotes Alpine, Python e Rust foi executada.

O download inicial pelo espelho expirou. A tentativa no repositório oficial `ghcr.io/aquasecurity/trivy-db:2` sofreu uma falha de stream HTTP/2; a transferência foi concluída usando HTTP/1.1 com `GODEBUG=http2client=0`. Essa alteração de transporte manteve TLS, a mesma base oficial e o critério de aprovação. O relatório não constitui uma garantia de ausência de vulnerabilidades fora do escopo ou depois dessa data.

Os arquivos locais de reprodução e relatórios completos estão em `.runtime/interface-package/`, ignorados pelo Git: `check_package.py`, `package-files-routes.json`, `image-inspect.json`, `image-platform-inspect.json`, `runtime.json`, `trivy.log` e `record_evidence.py`. A base está em `.runtime/trivy-cache/`. Os comandos de lint, formato, tipos e testes também constam em `commands.checks` no registro versionado.

Esta rodada não iniciou a stack de observabilidade, não gerou carga nem entregas operacionais de alertas. `publication.json` foi preservado. Em `interface-review.json`, somente o nome da branch interna foi omitido; resultados, baseline e hashes das fontes permanecem iguais. Os hashes dos documentos atuais estão no registro complementar. Alterações posteriores desta documentação não mudam a imagem, pois `docs/*` é excluído do build, com exceção de `docs/runbooks/`.

## Correção da exportação JUnit no CI

Na [primeira execução do candidato no GitHub](https://github.com/arthurjoanes/api-sentinel/actions/runs/35685290078), o commit `75094d5` passou por build, scan, análise estática, monitoramento e suíte isolada. A etapa HTTP exibiu sucesso nos 73 casos, mas o job falhou no encerramento do pytest: `PermissionError` ao criar `/artifacts/http-tests.xml`. Não houve JUnit HTTP dessa execução no artefato; o XML de mesmo nome dentro de `problem-review/20260921t064944662185z` pertence à prova histórica.

O serviço `tools` usa UID 0 com `cap_drop: ALL` e somente `CHOWN` adicional. Sem `DAC_OVERRIDE`, ele não pode criar o arquivo no diretório do bind pertencente ao runner Linux. O workflow agora prepara somente `artifacts/http-tests.xml`, com dono 0:0 e modo 0644, antes do pytest HTTP. O diretório já é criado pelo passo inicial de build; as permissões gerais, o usuário e as capabilities dos serviços não mudaram.

A correção foi conferida com Actionlint e um container descartável da imagem candidata, sem rede nem serviços: diretório Linux UID 1001/modo 0755, escritor UID 0 com somente `CHOWN`. A criação foi recusada antes da preparação; a escrita no arquivo UID 0/modo 0644 passou. Esse teste verifica a exportação e não substitui a execução completa do CI no commit corrigido.
