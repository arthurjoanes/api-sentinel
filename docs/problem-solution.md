# Problemas resolvidos e como conferir

Desenvolvi o laboratório para uma integração de lojas que consulta vendas e disponibilidade no ERP. Clientes, vendas e ERP são sintéticos. O resultado demonstrado é técnico: consultas com escopo correto, contenção de falhas e histórico verificável. Não houve piloto com operadores reais, medição de economia ou operação em produção.

## 1. Uma credencial não pode consultar a loja de outra organização

**Entrada → resultado:** a credencial da organização A lista as lojas 1, 2 e 3. Uma consulta à loja 4 recebe HTTP 403. Um resultado já em cache não dispensa essa autorização. Credenciais revogadas deixam de autenticar na consulta seguinte, inclusive quando ela chega a outro processo.

**Como:** implementei [authenticate e authorize](../src/api_sentinel/auth.py) para derivar a organização (tenant), as lojas e as permissões do registro da credencial. O [fluxo HTTP](../src/api_sentinel/app.py) autoriza antes da quota e do cache. A chave do resumo contém versão, tenant, loja e período. A identidade não vem de um parâmetro enviado pelo consumidor.

**Como conferir:** [integração PostgreSQL](../tests/integration/test_data_postgres.py), casos `test_cross_tenant_and_scope_rejected_before_business_query` e `test_expired_and_revocation_are_seen_by_both_process_pools`. O custo é consultar a credencial a cada requisição; o pool de autenticação tem orçamento próprio. Isso verifica isolamento no contrato da aplicação, não isolamento físico de bancos por cliente.

## 2. Três itens não são três pedidos

**Entrada:** a fixture de referência contém duas unidades de R$ 25,00 no pedido 101, uma de R$ 35,00 no mesmo pedido e uma de R$ 40,00 no pedido 102.

**Resultado:** receita de `12500` centavos, `2` pedidos e ticket médio de `6250` centavos. Uma venda à meia-noite do dia comercial seguinte fica fora da consulta do dia anterior. Consultar fora da cobertura conhecida recebe HTTP 422, em vez de um zero que pareceria válido.

**Como:** implementei em [queries.py](../src/api_sentinel/queries.py) a soma de quantidade × preço, a contagem de pares distintos de loja/pedido e a conversão de dias de São Paulo para um intervalo UTC com fim exclusivo. O ticket usa `Decimal` com `ROUND_HALF_UP`. A [fixture independente](../tests/unit/test_data_contract.py) fixa a conta; [testes com PostgreSQL](../tests/integration/test_data_postgres.py) conferem agregado, fronteira do dia e cobertura.

**Limite:** a massa é imutável e o contrato monetário é BRL em centavos. O projeto não implementa escrita de vendas, câmbio ou atualização transacional desse cache.

## 3. O ERP lento não deve ocupar todos os recursos das vendas

**Entrada → resultado:** o simulador pode enviar chunks continuamente, sem ficar inativo tempo suficiente para um timeout de leitura. A chamada ERP ainda termina pelo prazo total. O circuito e o limite de quatro chamadas por processo contêm esse caminho; resumos usam PostgreSQL e não dependem da resposta do ERP.

**Como:** [erp.py](../src/api_sentinel/erp.py) usa cliente reutilizado, admissão própria, orçamento total de 900 ms, limite de bytes e circuito por processo. Redirects, compressão e formatos inesperados são recusados. Um retry elegível consome o mesmo orçamento. [Testes do runtime](../tests/unit/test_runtime.py) exercitam chunks contínuos, resposta excessiva e validação da resposta.

**Prova de coexistência:** testes isolados não demonstram sozinhos ERP lento e vendas simultâneas. Essa medição pertence às execuções identificadas em [verificação](verification.md) e [desempenho](performance.md), com clientes de carga, resultado comercial conhecido e recuperação. Na [execução completa de 22/09 às 12:12 UTC](evidence/editorial-20260922/full-run.json), a mistura com ERP degradado concluiu 151 requisições: 114 respostas válidas e 37 falhas previstas do ERP, sem resultados inválidos ou iterações descartadas. A recuperação concluiu 100/100 válidas. São observações desse laboratório, não uma garantia de disponibilidade do ERP. A [prova anterior](evidence/publication.json) permanece identificada separadamente.

## 4. Duas réplicas não podem duplicar a quota

**Entrada → resultado:** dois clientes Redis fazem 30 tentativas concorrentes para a mesma organização com limite 10. O [teste real de Redis](../tests/integration/test_runtime.py), `test_atomic_global_quota_shared_between_clients`, exige 10 admissões e 20 recusas HTTP 429 dentro da mesma janela. O TTL precisa existir e ser de até um segundo.

**Como:** coordenei o incremento e a expiração na mesma operação Redis em [enforce_quota](../src/api_sentinel/admission.py). O limite comercial configurado é 30/s por tenant; 10/s é o parâmetro explícito desse teste e o limite do tenant técnico do probe. A [admissão](../src/api_sentinel/admission.py) limita trabalho em andamento separadamente: excesso de capacidade recebe 503, não 429.

Na [execução pelo proxy](evidence/editorial-20260922/full-run.json), uma réplica admitiu 300 de 600 chamadas; duas admitiram 300 de 601. As restantes receberam 429, sem recusas de capacidade. Esses ensaios de dez segundos complementam o teste atômico; seus denominadores estão em [desempenho](performance.md).

**Custo e limite:** a quota depende de Redis e falha fechada com 503 se ele não responde. A janela fixa permite rajadas na fronteira; não é uma janela deslizante. Concorrência, circuito e pools continuam locais a cada réplica.

## 5. Cache compartilhado sem trabalho duplicado ilimitado

**Entrada → resultado:** oito pedidos concorrentes da mesma chave provocam um cálculo; o hit seguinte não recalcula. Depois de expirar, a nova rodada volta a ter um preenchimento. Um dono antigo não pode apagar o lock adquirido por outro processo.

**Como:** [cache.py](../src/api_sentinel/cache.py) usa lock com token, TTL de dois segundos, remoção condicional e espera limitada a 250 ms. O dado permanece por 15 segundos. [test_cache_stampede_expiry_and_owner_token](../tests/integration/test_runtime.py) verifica computações e propriedade do lock, além do conteúdo.

**Falhas diferentes:** se apenas o cliente de cache falha, o cálculo pode seguir dentro da admissão comercial. Se Redis inteiro cai, a quota anterior falha fechada e não libera consultas SQL irrestritas. As ACLs separam comandos/chaves, mas quota e cache compartilham a disponibilidade do mesmo processo Redis.

## 6. Um alerta repetido não é uma nova ocorrência

**Entrada → resultado:** `firing → firing → resolved → firing atrasado`, com o mesmo fingerprint e início, mantém um incidente e quatro entregas. O último firing entra no histórico sem reabrir a ocorrência. Uma recuperação de início antigo não fecha uma ocorrência nova.

**Como:** implementei em [storage.py](../alert_receiver/storage.py) a persistência do incidente e dos eventos na mesma transação, com identidade por fingerprint + `startsAt`. Os [testes do receiver](../tests/unit/test_receiver.py) cobrem repetição, ordem invertida, concorrência e rollback de um lote. HTTP 2xx do webhook significa que a gravação terminou, não uma promessa de entrega exatamente uma vez.

**Na interface:** central → filtro → ocorrência → runbook → retorno preserva filtro e referência. “Finalizados” reúne dois estados visuais: “Resolvido” exige a recuperação recebida; “Encerrado pelo operador” tem indicação neutra e explica a ausência desse webhook. A reconciliação administrativa existente é restrita ao alerta de perda de réplica da demo e não acrescenta uma entrega fictícia.

Uma consulta do probe validada também não comprova saúde global. Resultado vencido perde a indicação de validação; probe desativado ou sem observação não aparece saudável. [UI](../alert_receiver/ui.py), [expiração no navegador](../alert_receiver/snapshot.js) e [testes de estados](../tests/unit/test_receiver_ui.py) preservam essa distinção. Os links de investigação usam a configuração da mesma execução; sem ela, a navegação mostra erro explícito. Não há fallback para ferramentas de outra stack.

A [história operacional](operational-story.md) mostra entregas reais e a mesma ocorrência recuperada. O cenário de entrega antiga fora de ordem é verificado pelos testes automatizados; não atribuo quatro entregas a uma captura que registra apenas duas.

## O que mudou depois das medições

Em 21/09/2026, duas tentativas de quota tiveram 300 respostas corretas, 299 recusas 429 e duas recusas 503 em 601 conclusões. Aquecimento não eliminou o problema. Os contadores localizaram as recusas na admissão de autenticação, sem demonstrar a causa subjacente da espera. O limite foi de quatro para oito operações, mantendo pool de duas conexões, aquisição de 200 ms e prazo de 500 ms. O [teste de admissão](../tests/unit/test_auth_admission.py) exige recusa da nona e liberação após cancelamento.

As tentativas e medições posteriores permanecem em [verification.md](verification.md) e [performance.md](performance.md). A central foi redesenhada depois da primeira prova operacional; [interface-validation.md](interface-validation.md) registra testes e capturas com esse escopo separado. Nenhuma captura sintética comprova entrega operacional de alerta ou disponibilidade mensal.

Uma resposta 200 com tenant ou valor incorreto, Redis indisponível liberando SQL protegido, ERP lento derrubando as consultas independentes ou recuperação sem voltar à fixture conhecida reprova a demonstração. Reduzir latência global por meio de recusas rápidas não satisfaz esses critérios.
