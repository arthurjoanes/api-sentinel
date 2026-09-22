# Qualidade da interface do receiver

## Produto e escopo

O operador deste laboratório usa a central para escolher qual ocorrência investigar,
conferir como mudou de estado e abrir um procedimento. A interface apresenta registros
do receiver; métricas e traces continuam no Grafana, Prometheus e Jaeger. Nenhuma
ausência de incidentes autoriza inferir disponibilidade global.

Esta revisão parte de `be419e0255ca5cfc4b1afe4514f854e1c067161a`. Python gera HTML
escapado em [ui.py](../alert_receiver/ui.py); [styles.css](../alert_receiver/styles.css)
define o layout e [snapshot.js](../alert_receiver/snapshot.js) vence a observação e
orienta o foco. Não existe React ou Next.js neste frontend. As recomendações
específicas de hooks, Server Components e bundles React não se aplicam; a revisão
mantém HTML no servidor, fontes do sistema e JavaScript pequeno, sem novas dependências.

## Direção e padrões

A fila é uma superfície contínua de trabalho. Estado, ocorrência/impacto, momento e
ação usam eixos comparáveis; filtros, totais e atualização pertencem a essa superfície.
A observação do probe vem depois da fila, com atalho no cabeçalho, validade e detalhes
expandíveis. O detalhe agrupa a decisão atual e separa o histórico. O catálogo é um
diretório de procedimentos, sem números que sugeririam uma sequência inexistente.

```text
API Sentinel | Incidentes | Runbooks                      laboratório
Ferramentas: métricas / traces / coleta
+ Incidentes --------------------------------- Atualizar leitura +
| Todos / Em andamento / Finalizados      registros · Ver probe  |
| Estado       Ocorrência e impacto         Momento      Ação     |
| ... linhas comparáveis; metadados por expansão ...             |
+ Retenção e atualização manual --------------------------------+
Observação do probe                     Última consulta / detalhes
Detalhes da observação                   Período e histórico
```

- Base: navy `#142438`, tinta `#172536`, fundo `#edf1f6`, linha `#ccd5e0`, texto
  secundário `#526176` e ação azul `#155acb`. Estados têm tokens separados:
  recuperação `#16623e`, alerta `#a52c35`, observação vencida/falha de configuração
  `#815711`. Encerramento manual é neutro. Texto e rótulos sempre acompanham a cor.
- Tipografia local Segoe UI/Arial; títulos 23–28 px, conteúdo 13–14 px,
  metadados 12 px. Consolas somente em código. Números e horários são tabulares.
- Área útil centralizada, máximo de 1380 px, margens 32 px desktop/16 px mobile.
  Ritmo de 4/8/16/24 px; linhas crescem com conteúdo, sem truncar impacto ou título.
- Botões e links são elementos nativos. Foco visível de 3 px, primeiro link pula
  para o conteúdo. Hover de botão varia opacidade em 180 ms; reduced-motion remove
  a transição. Nada pulsa para simular atividade.
- Até 800 px a fila reorganiza colunas; até 600 px cada ocorrência mantém estado,
  ação, descrição e momento. Em 320 px a ação divide a linha com o registro.
  Código pode rolar no próprio bloco, focável por teclado. A página não deve rolar
  horizontalmente. O sumário do runbook precede o artigo no DOM e no layout.

## Semântica preservada

- Filtros `all`, `firing`, `resolved` continuam na URL. Finalizados reúne recuperação
  e encerramento manual; contadores usam a mesma leitura, não entregas acumuladas.
  Limite de 100 registros não vira paginação implícita. Ordenação permanece ativa
  primeiro e recente depois; a interface não oferece ordenação arbitrária/exportação.
- O momento em andamento é a última entrega; nos finalizados é recuperação ou
  encerramento. Datas são UTC, sem inventar relativo ou duração indisponível.
- Recuperação recebida → próximo passo é conferir observação/métricas atuais.
  Encerramento manual → conferir motivo e observação, sem afirmar recuperação.
  A instrução original do alerta permanece consultável como registro histórico.
- Probe mede somente a consulta autenticada de referência. Sucesso recente,
  resultado vencido, falha, pendência, desativação e configuração inválida são
  distintos. Zero milissegundos é um valor; duração ausente é “Não medida”.
- Controles são de leitura. Autenticação do webhook, deduplicação, eventos atrasados,
  retenção, isolamento comercial e destinos locais permitidos não mudaram.

## Referências e decisões

As skills `frontend-design` e `web-design-guidelines` orientaram composição,
hierarquia, teclado, contraste, movimento e revisão. As diretrizes foram consultadas
na [fonte mantida pela Vercel](https://github.com/vercel-labs/web-interface-guidelines/blob/main/command.md)
em 22/09/2026. A avaliação é técnica; não houve estudo com usuários nem alegação de
que estes layouts foram aprovados empiricamente.

| Referência | Padrão adotado | Limite / rejeição |
| --- | --- | --- |
| [Grafana Alert list](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/visualizations/alert-list/) e [demonstração pública](https://play.grafana.org/d/bdodlcyou483ke/) | Estados e identidade comparáveis, destino de investigação explícito | Sem painel de métricas ou classificação que o receiver não calcula |
| [Karma](https://github.com/prymitive/karma), Apache-2.0, referência `dcd13b85d252b6ca3bd86df62524e00ffa56a7dc` | Filtros junto da fila, observação densa sem esconder o estado | Não copiar todos os labels, silêncios ou agrupamentos inexistentes neste produto |
| [cState](https://github.com/cstate/cstate), MIT, referência `3c1e61c7277d71434246ca2f6a778b7e5eb856c1` | Recuperação legível e cronologia separada | Página pública de status não é fila de triagem; nenhum “tudo operacional” inferido |
| [Carbon dashboards](https://carbondesignsystem.com/data-visualization/dashboards/) | Relação entre informação, tarefa e densidade | Não criar KPIs para ocupar espaço |

Nenhum código, fonte, ícone ou imagem dessas referências foi incorporado ao produto.
As referências visuais servem para decisões documentadas, sem cópia de um template.

## Inventário, diagnóstico e validação

| Família / telas cobertas | Operador, tarefa e dados | Ação principal |
| --- | --- | --- |
| C — `/`, `?status=all`, `firing`, `resolved`; vazio e 100 registros | Triagem por estado; contagens, resumo, impacto e momento do receiver | Filtrar e abrir a ocorrência |
| D — `/incidents/{id}` ativo, recuperado, encerrado manualmente | Entender estado atual e reconstruir entregas, inclusive repetidas/atrasadas | Ativo: runbook; finalizado: conferir observação atual |
| R — `/runbooks` | Escolher entre sete condições documentadas | Abrir procedimento |
| P — `/runbooks/{slug}`: unavailable, replica, error-budget, latency, saturation, erp, telemetry | Localizar diagnóstico e comandos preservados no Markdown | Ir à seção e retornar à ocorrência |
| E — 404 ocorrência/runbook inexistente, 422 parâmetro inválido, 503 histórico/ferramenta indisponível | Reconhecer falha de leitura/configuração; não confundir com vazio | Voltar à central e tentar novamente |
| Componente de C — observação e detalhes | Sucesso recente, vencido, falha, pendente, desativado, configuração ou horário inválido; duração e resultado ausentes | Conferir validade e abrir detalhes |

Grafana, Jaeger, Prometheus e Swagger são superfícies de terceiros, não renderizadas
por este frontend. Os links e seus fallbacks locais estão no escopo; não foram
reimplementados. Não há formulário de escrita, seleção múltipla, paginação,
exportação ou ordenação manual na central. Carregamento é navegação de documento
nativa, sem cache de respostas compartilhado no cliente nem spinner inventado.

### Achados e correções

| Prioridade / local | Evidência inicial e impacto | Correção / validação |
| --- | --- | --- |
| P1 — D, `incident_detail` | Próximo passo repetia a ação do alerta mesmo finalizado; induzia intervenção desnecessária | Ação depende do estado; original preservado em Datas e entregas. Regressão parametrizada nos três estados e jornada recuperado → observação |
| P2 — C, `incident_row` e `home` | Linhas de 139 px em 1440, com estado e identificação desalinhados entre ocorrências | Colunas contínuas e filtros integrados; mesma primeira linha passa a 100 px, dados equivalentes nos três filtros |
| P2 — C, observação/vazio | Probe ocupava coluna própria; vazio alto competia com a decisão | Faixa auxiliar com atalho e detalhes; vazio compacto, sem afirmar saúde |
| P2 — shell e componentes | Verde identificava marca, navegação e recuperação; metadados pequenos demais | Navy/azul para navegação, cores semânticas independentes, 12 px para metadados; contraste medido |
| P2 — P, sumário e código | Sumário tinha ordem visual diferente do DOM em mobile; blocos de código não recebiam foco | DOM e layout têm mesma ordem, código focável; teclado em 320 px |
| P2 — C/D, retorno à observação | Na nova jornada entre documentos, o navegador removia o foco aplicado pelo script deferido | `pageshow` reaplica destino explícito depois do fragmento nativo; regressão de teclado reproduziu a falha antes da correção |
| P3 — R, catálogo | Números grandes sugeriam sequência entre procedimentos independentes | Diretório por condição e descrição, sem numeração artificial; sete destinos preservados |

### Matriz antes → depois

Estados: **C** = Conforme; **P** = Parcialmente conforme; **NC** = Não conforme;
**NV** = Não verificado; **NA** = Não aplicável. “Conforme” se refere ao critério
e aos cenários descritos, não a uma certificação geral. Cada coluna é uma família
com o inventário completo acima; variantes compartilham os mesmos renderizadores.

| Dimensão | C — central e probe | D — detalhe | R — catálogo | P — sete procedimentos | E — erros |
| --- | --- | --- | --- | --- | --- |
| 1. Objetivo e público | P → C: fila precede observação | NC → C: ação considera recuperação | C → C: escolha por condição | C → C: executar diagnóstico | C → C: recuperar navegação |
| 2. Hierarquia e organização | P → C: filtros e linhas juntos | NC → C: decisão atual/histórico distintos | P → C: diretório, sem sequência fictícia | P → C: sumário antes do texto | P → C: falha e próximo destino agrupados |
| 3. Grid, espaçamento e densidade | P → C: colunas comparáveis | P → C: bloco de decisão e contexto subordinado | P → C: sete linhas, sem cards altos | P → C: leitura limitada e sumário lateral | P → C: aviso compacto alinhado ao conteúdo |
| 4. Tipografia, cor e consistência | P → C: ação azul, estados separados | P → C: recuperação verde, manual neutro | P → C: títulos e descrições consistentes | P → C: texto 14 px, código 12 px | P → C: mesmo shell e foco |
| 5. Indicadores, gráficos e tabelas | C → C: contagem/entregas/validade separados | P → C: impacto explicitamente histórico | NA → NA: sem indicadores | C → C: números/comandos originais | NA → NA: sem indicadores |
| 6. Navegação, filtros e ações | C → C: URL/filtro/retorno; atalho probe | P → C: ação contextual e retorno focado | C → C: todos os links preservados | P → C: ordem DOM e teclado | C → C: volta à central |
| 7. Carga, vazio, erro, atualização | P → C: vazio conciso, probe vence sem refresh | C → C: falta de eventos continua explícita | NA → NA: catálogo estático | C → C: erro de runbook preservado | C → C: 404/422/503 não viram sucesso vazio |
| 8. Acessibilidade e responsividade | P → P: teclado/contraste/reflow verificados; leitor de tela não | P → P: mesma limitação | P → P: mesma limitação | P → P: código focável; zoom nativo não medido | P → P: recuperação por teclado; mesma limitação |
| 9. Desempenho | NV → P: 100 linhas medidas localmente; sem campo/SLA | NV → P: sem nova dependência; latência de campo não medida | NV → P: HTML estático; sem benchmark de campo | NV → P: fontes locais e zero requests externos | NV → P: HTML mínimo; sem benchmark de campo |
| 10. Manutenção e reutilização | P → C: shell/tokens/linha reaproveitados | P → C: regra de apresentação testada | P → C: mesmo diretório de runbooks | C → C: Markdown e parser restrito preservados | C → C: um renderer de problemas |
| 11. Dados, regras e permissões | C → C: contagens e metadados comparados | C → C: estado persistido/dedup não mudam | NA → NA: não lê dados de tenants | C → C: procedimentos não executam ações | C → C: HTML/JSON e destinos locais mantidos |

As provas históricas em `interface-validation.md` e `operational-story.md`
conservam suas próprias imagens, fontes e datas.

## Antes/depois e resultados

O [comparativo](evidence/frontend-quality/comparison.json) executa o renderizador
de `be419e0` e o candidato sobre o **mesmo SQLite**, com os mesmos IDs, títulos,
impactos, entregas e horários. Altura de viewport: 1000 px; larguras: 1920, 1440,
768, 390 e 320 px CSS. O aviso sintético aparece nos dois lados.

| Recorte | Antes | Depois | Leitura |
| --- | --- | --- | --- |
| Central, 1440 px, todos | primeira linha em 383 px; altura 139 px | primeira linha em 371 px; altura 100 px | Mais área da fila usada para comparação |
| Central, 390 px, todos | primeira linha 462 px / 207 px; 2 inteiras | primeira linha 443 px / 182 px; 3 inteiras | Conteúdo permanece completo |
| Central, 320 px, todos | primeira linha 462 px / 231 px | primeira linha 492 px / 198 px | Botão de atualização quebra linha; troca deliberada por alvo legível |
| Detalhe recuperado, 1440 px | cabeçalho 278 px, ação original tratada como atual | cabeçalho 316 px, recuperação e verificação atual explícitas | Crescimento ligado à decisão correta, não alegação de maior densidade |

Links diretos: [antes 1440](screenshots/frontend-quality/comparison/baseline-all-1440.png),
[depois 1440](screenshots/frontend-quality/comparison/candidate-all-1440.png),
[antes 390](screenshots/frontend-quality/comparison/baseline-all-390.png),
[depois 390](screenshots/frontend-quality/comparison/candidate-all-390.png),
[detalhe recuperado](screenshots/frontend-quality/candidate/recovered-detail.png),
[encerramento manual](screenshots/frontend-quality/candidate/manual-detail.png),
[catálogo](screenshots/frontend-quality/candidate/runbook-catalog.png) e
[procedimento](screenshots/frontend-quality/candidate/runbook-context.png).
São medições de geometria e inspeção técnica, não prova de produtividade.

| Verificação | Resultado e escopo |
| --- | --- |
| Build Docker | Candidato `pf-api-sentinel-quality:20260922`; identidade e 117 arquivos empacotados no [registro](evidence/frontend-quality/package.json) |
| Ruff / formato / mypy na imagem | Sem erro; 70 arquivos Python formatados, 27 alvos de tipos |
| `pytest tests/unit` na imagem, sem fontes montadas | 236 testes + 11 subtests aprovados. Três casos de acesso por UID exigem root e foram pulados nesse processo não privilegiado; os mesmos três passaram em container separado com root e capabilities limitadas. Dois avisos existentes Starlette/anyio |
| HTTP em processo na imagem | 20 rotas; central, assets, 7 runbooks, 404, 422, 503 e bytes servidos iguais aos assets empacotados |
| Browser Edge / Playwright | [12 jornadas](evidence/frontend-quality/browser-review.json), 26 rotas/estados × 5 larguras = 130 recortes; nenhum erro JavaScript ou overflow da página |
| Retorno, teclado e foco | Filtro → ocorrência → runbook → seção → retorno à linha; fallback ao conteúdo se a linha não estiver no filtro; skip link; recuperação → observação com filtro e foco no summary. Blocos de código focáveis |
| Estados | Recuperação, manual, firing atrasado, probe recente/vencido/desativado/falha, vazio, texto longo e falhas 404/422/503; detalhes e instrução original acessíveis por expansão |
| Troca rápida de filtros | Requisição firing atrasada 250 ms seguida de resolved: resultado final permanece resolved. É navegação nativa de documento, sem mistura de respostas no cliente |
| Dados equivalentes | [Comparação por DOM](evidence/frontend-quality/extended-review.json) de estado, ID, título, impacto, momento e entregas nos três filtros |
| Contraste e alinhamento | [40 combinações](evidence/frontend-quality/visual-audit.json) de texto/fundo calculado; menor razão 5,12:1, eixos de marca/conteúdo alinhados. [Limites essenciais](evidence/frontend-quality/disclosure-review.json): botão secundário 3,30:1, foco ≥5,51:1, seleção no navy 4,89:1 |
| Alvos e movimento | Seis telas mobile sem link/summary menor que 24×24 px; foco visível e reduced-motion conferidos. Sem animação de falsa atividade |
| Segurança do pacote | Trivy 0.74.0 fixado pelo CI, base atualizada em 22/09/2026 às 02:00 UTC e válida até 23/09/2026 às 02:00 UTC, reutilizada offline. Zero achados em Alpine/Python/uv; bloqueio HIGH/CRITICAL sem exceções. Aviso do scanner sobre lista EOL de Alpine 3.24 registrado |
| Segredos | [Gitleaks 8.30.1](evidence/frontend-quality/secret-scan.json): histórico Git completo e arquivos rastreados/novos, também normalizados para LF; zero achados, sem alterar a allowlist |

O ensaio local de 100 ocorrências manteve um script e zero recursos externos.
O HTML passou de 90.725 para 87.678 bytes e o DOM de 2.511 para 2.413 elementos.
Cinco navegações aquecidas, após uma inicial, deram medianas de DOMContentLoaded
de 26,1 → 27,0 ms no desktop e 27,8 → 27,6 ms no recorte mobile. A variação pequena
e o ambiente sem throttling não sustentam ganho de velocidade percebida. Não foi
adicionada virtualização: o limite existente é 100, o custo local é pequeno e
preservar busca, seleção e foco nativos evita complexidade sem evidência de gargalo.
Não se mediu INP, LCP em campo, rede móvel nem hardware de telefone.

## Reprodução, limites e continuidade

Os [helpers e comandos](evidence/frontend-quality/reproduce/README.md) distinguem
preview sintético, browser e validação dentro da imagem. Relatórios e hashes desta
rodada ficam em `docs/evidence/frontend-quality/`; capturas em
`docs/screenshots/frontend-quality/`. Evidências anteriores não foram regravadas.

- P2 — Não verificado: leitor de tela, zoom nativo do Edge, Safari/Firefox e telefone
  físico. 640/320 px CSS verificam reflow equivalente a 200%/400% de uma janela de
  1280 px, sem alegar que o zoom real foi acionado. Não há certificação WCAG.
- P2 — Fora desta rodada: nova carga, PostgreSQL/Redis em integração, stack completa
  de alertas, entrega operacional e isolamento entre tenants por HTTP real. As
  suítes unitárias de autorização passam; não substituem a prova de integração.
- P3 — Não aplicável na UI: valores financeiros negativos, gráfico, exportação,
  ordenação manual, edição e permissão de escrita. O frontend mostra contagens
  inteiras de registros, nunca uma nova agregação comercial. Zero e dados ausentes
  permanecem distintos; a regra `duration_seconds is not None` conserva duração zero.
- P3 — O limite de 100 registros pode exigir consulta JSON/armazenamento para uma
  investigação maior. A revisão não adiciona paginação ou simula acesso a todo o
  histórico retido.

Revisão final pelas diretrizes: `ui.py` mantém HTML escapado, links nativos e uma
hierarquia de títulos; `styles.css` mantém reflow, contraste e movimento reduzido;
`snapshot.js` não faz polling nem muda filtros. A data UTC fixa em Python é o
contrato local documentado, sem hidratação/client-side locale; recomendações de
Intl/React não justificam introduzir outro runtime. Títulos PT-BR usam caixa de
frase, e virtualização foi deliberadamente descartada pela medição acima.
