# Decisões técnicas e seus custos

Estas decisões correspondem ao código executável do laboratório. Os exemplos de entrada e resultado estão em [problema e solução](problem-solution.md); os limites configurados e os fluxos completos, em [arquitetura](architecture.md).

## Problema central e dificuldades registradas

O resultado procurado é uma consulta correta e autorizada, com recursos limitados, mesmo durante falhas parciais. Uma resposta rápida com valor errado, acesso a outra organização ou perda silenciosa da observação não atende a esse objetivo. Os motivos abaixo explicam o desenho técnico; não representam relato de um cliente real ou medição de economia.

| Dificuldade observada | Decisão ou tratamento | O que a evidência permite concluir |
| --- | --- | --- |
| Um ERP que envia pequenos trechos continuamente pode nunca atingir um timeout de inatividade | Prazo total para corpo e validação, com limite de chamadas simultâneas e circuito próprios | Os testes cobrem o contrato de encerramento. A coexistência com consultas comerciais pertence à execução identificada em [desempenho](performance.md). |
| Tentativas de quota tiveram recusas de capacidade e outra execução perdeu iterações no gerador | Separar quota, admissão, espera de conexão, resultado correto e iterações não iniciadas; preservar as tentativas reprovadas | O ensaio posterior passou, mas isso não comprova a causa inicial. Não atribuir todo o ganho a uma única alteração. |
| Uma entrega de alerta pode repetir ou chegar depois da recuperação | Persistir a ocorrência e seu histórico por identidade estável; diferenciar recuperação de encerramento manual | Regressões verificam o estado final; capturas sintéticas verificam apresentação, sem comprovar entrega pela rede. |
| O CI aprovou 73 casos HTTP, mas não conseguiu escrever o XML de resultado | Preparar o arquivo de saída com dono/permissões necessários, preservando as restrições gerais do container | A correção `b5f0eed` trata a exportação. A [nota de validação](interface-validation.md#correção-da-exportação-junit-no-ci) conserva a falha e o teste específico de permissões. |
| A preparação de um snapshot omitiu a fixture financeira porque ela não fazia parte do inventário de fontes do runner | Incluir `data/` no [fingerprint](../scripts/review.py); conferir que mudar o valor da fixture altera a identidade das fontes | A [regressão](../tests/unit/test_review_cleanup.py) falhou com o inventário anterior e passou após a inclusão. A falha de preparação é distinta de uma regressão da API; os registros históricos não foram renomeados. |

Para cada escolha a seguir, o motivo explica qual erro ela evita; o custo indica o que precisa ser operado ou reavaliado. O [mapa de componentes](architecture.md#o-requisito-que-justifica-cada-parte) identifica quando uma alternativa menor pode bastar.

## Autorizar antes de consultar cache ou dependência

**Decisão:** em [app.py](../src/api_sentinel/app.py), a credencial passa por [auth.py](../src/api_sentinel/auth.py) antes do cache/SQL/ERP. Tenant, lojas e escopos vêm do banco. Autenticação usa pool separado e prazo de 500 ms; a conexão é devolvida antes de aguardar o ERP.

**Motivo:** um cache aquecido não pode contornar o acesso à loja, e uma integração lenta não deve reter conexões de autenticação. Revogação precisa ser observada por ambas as réplicas na próxima consulta.

**Custo e limite:** toda chamada autenticada faz uma leitura no banco; hash da credencial não dispensa proteção do segredo original. São duas conexões de autenticação e quatro de negócio por processo, sem overflow: duas réplicas podem usar 12, além das ferramentas. [Integração de dados](../tests/integration/test_data_postgres.py) verifica revogação e autorização; [admissão de autenticação](../tests/unit/test_auth_admission.py) verifica limite e cancelamento.

## Dinheiro inteiro, período comercial e cursor ligado ao escopo

**Decisão:** [queries.py](../src/api_sentinel/queries.py) calcula centavos inteiros e pedidos distintos; o ticket médio usa `ROUND_HALF_UP`. Datas comerciais são convertidas em início inclusivo/fim exclusivo UTC. SQL usa parâmetros vinculados. Vendas são ordenadas por `(sold_at, id)` decrescente e a consulta lê no máximo `limit + 1` itens.

**Motivo:** itens do mesmo pedido não devem inflar o denominador; datas UTC não representam necessariamente o dia de São Paulo. O desempate por ID evita repetir ou pular vendas com o mesmo horário. O [cursor assinado](../src/api_sentinel/cursor.py) inclui tenant, loja, período e versão, para impedir seu reaproveitamento em outra consulta.

**Custo e limite:** alterar a versão do dataset invalida o cursor; assinatura não torna seu conteúdo secreto. A massa imutável simplifica a paginação. Escritas concorrentes exigiriam outro contrato. [Fixture e contrato](../tests/unit/test_data_contract.py) conferem arredondamento e escopo; [PostgreSQL real](../tests/integration/test_data_postgres.py) confere fronteira de data e desempate sem duplicatas.

## Quota distribuída e admissão imediata têm funções diferentes

**Decisão:** [enforce_quota](../src/api_sentinel/admission.py) coordena chegadas por tenant com Lua atômico no Redis. [admission.py](../src/api_sentinel/admission.py) limita simultaneidade no processo e recusa imediatamente ao atingir o limite. HTTP 429 representa quota; HTTP 503 representa capacidade ou dependência indisponível.

**Motivo:** duplicar réplicas não pode duplicar o limite comercial. Um pool limita conexões, mas não impede uma fila crescente de requisições à espera. Separar os códigos mantém recusas de quota distintas de falhas no [SLI](slo.md).

**Custo e limite:** pode haver rajada na fronteira da janela fixa de 1 s. Redis é dependência obrigatória e indisponibilidade falha fechada. A justiça da admissão é local; não há escalonador global. [Redis concorrente](../tests/integration/test_runtime.py) confere a quota entre clientes; [runtime](../tests/unit/test_runtime.py) confere recusa e devolução de capacidade após cancelamento.

## Cache com propriedade do lock e frescor explícito

**Decisão:** [cache.py](../src/api_sentinel/cache.py) usa lock com token aleatório, TTL de 2 s e remoção condicional. Espera pelo preenchimento: até 250 ms. TTL do resultado: 15 s. O chamador inclui versão, tenant, loja e período na chave.

**Motivo:** reduzir SQL duplicado sem servir o resultado de outro escopo e sem permitir que um preenchimento atrasado apague o lock do novo dono. `observed_at` e `cache_age_seconds` mostram a idade do cálculo; um hit não torna a massa mais nova.

**Custo e limite:** contenção prolongada recebe `cache_fill_busy`. Falha apenas no cache permite fallback protegido pela admissão; falha da quota não permite. Os usuários ACL são distintos, mas o processo Redis é compartilhado. A [integração Redis](../tests/integration/test_runtime.py) mede o número de cálculos e verifica propriedade do lock e negação de comandos/chaves indevidos.

## Prazo total e circuito próprios para o ERP

**Decisão:** [erp.py](../src/api_sentinel/erp.py) mantém cliente/pool reutilizados, no máximo quatro consultas por processo, deadline total de 900 ms e circuito local após falhas. O retry elegível cabe nesse mesmo orçamento. O consumidor fornece loja/SKU; o destino vem da configuração, com redirects e proxies herdados desabilitados.

**Motivo:** chunks periódicos podem impedir um read timeout sem concluir o corpo. O orçamento total cobre esse caso; limite de bytes e validação impedem aceitar resposta excessiva ou incompatível. Consultas comerciais não precisam do ERP para responder.

**Custo e limite:** cada réplica observa o circuito separadamente. Uma falha transitória pode resultar em recusa até a tentativa de recuperação. Não há fila persistente nem garantia de disponibilidade do fornecedor. [Testes de runtime](../tests/unit/test_runtime.py) exercitam trickle, cancelamento, compressão e tamanho; a coexistência sob carga tem prova separada em [performance.md](performance.md).

## Histórico durável e uma interface que não inventa recuperação

**Decisão:** [storage.py](../alert_receiver/storage.py) grava a ocorrência e seus eventos em uma transação SQLite antes de confirmar o webhook. Fingerprint + início identifica a ocorrência. A reconciliação manual registra a ação administrativa sem incrementar entregas nem fabricar um webhook.

**Motivo:** entregas podem repetir ou chegar fora de ordem. Um firing atrasado não pode reabrir um incidente recuperado; uma resolução antiga não pode encerrar a nova ocorrência. Por isso, a UI usa “Finalizados” no agrupamento e distingue “Resolvido” de “Encerrado pelo operador” em cada registro.

**Custo e limite:** armazenamento local em volume, sem cluster de receivers. Retenção de 30 dias para finalizados, ativos sem expiração; a lista mostra até 100 registros e o detalhe até 100 eventos recentes. Contagem acumulada de entregas pode superar eventos retidos. [Testes do receiver](../tests/unit/test_receiver.py) cobrem concorrência, rollback e transições; [retenção](../tests/unit/test_receiver_retention.py) cobre a janela.

## HTML no servidor, retorno explícito e investigação no ambiente certo

**Decisão:** [ui.py](../alert_receiver/ui.py) gera HTML sem framework frontend, escapa metadados e oferece links normais. Filtro tipado e ID limitado preservam central → detalhe → runbook → retorno, sem aceitar uma URL arbitrária de redirecionamento. A atualização é manual; [snapshot.js](../alert_receiver/snapshot.js) apenas vence a observação, abre seus detalhes e orienta o foco de retorno.

**Motivo:** a central precisa de histórico e procedimentos, sem uma segunda fonte de métricas. Grafana, Jaeger e Prometheus seguem acessíveis pelos destinos validados em [diagnostics.py](../alert_receiver/diagnostics.py). Configuração ausente apresenta erro, sem encaminhar para outra stack.

**Custo e limite:** a página é uma leitura do instante; alterações exigem atualização. Sem JavaScript, o resultado do probe só é reavaliado no próximo carregamento. O renderer dos runbooks suporta títulos, listas e código, não Markdown completo. A UI não calcula métricas por tenant ou disponibilidade global. [Testes da interface](../tests/unit/test_receiver_ui.py), [rotas](../tests/unit/test_receiver.py) e [investigação](../tests/unit/test_receiver_diagnostics.py) conferem esses contratos.

**Composição da triagem:** [ui.py](../alert_receiver/ui.py) e [styles.css](../alert_receiver/styles.css) mantêm estado, impacto, momento relevante e investigação em uma lista linear. Filtros têm contagens subordinadas ao rótulo; IDs e entregas abrem por expansão. O motivo é permitir escolher uma ocorrência antes de ler seu diagnóstico. O custo é uma interação adicional para metadados; estado e impacto continuam visíveis. A cronologia usa separadores simples, preservando a diferença entre recuperação, entrega atrasada e ação manual. A [comparação com o baseline](interface-validation.md) mede ocupação da tela com os mesmos dados sintéticos; não demonstra ganho de produtividade nem aprovação de usuários.

## Separar observação, diagnóstico e prova

**Decisão:** o [probe](../alert_receiver/probe.py) usa tenant próprio e confere pelo proxy o resultado fixo de R$ 125,00, dois pedidos e ticket de R$ 62,50. O vencimento da observação é explícito. Métricas usam populações definidas; traces são amostrados em 25%.

**Motivo:** “sem incidentes” não significa “saudável”, e um alerta informa sintoma, não causa. Investigar envolve comparar duração total, aquisição de conexão, SQL, cache e ERP, com um trace existente e logs correlacionados. Uma consulta bem-sucedida também não prova disponibilidade de todas as réplicas ou entrega dos alertas.

**Custo e limite:** um request pode não ter trace; Jaeger usa memória. Duas réplicas no mesmo host compartilham falhas. A referência de SLO de 30 dias não é resultado de uma demo curta. [Probe](../tests/unit/test_receiver_probe.py), [SLO](slo.md) e [verificação](verification.md) documentam o que foi testado e o que não foi medido. Nenhuma integração Azure ou ingestão em serviços externos está implementada.
