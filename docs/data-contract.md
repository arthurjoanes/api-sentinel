# Contrato de dados e consultas

O contrato é implementado pelo [seed](../src/api_sentinel/seed.py), [modelos](../src/api_sentinel/models.py), [consultas](../src/api_sentinel/queries.py), [cursor](../src/api_sentinel/cursor.py) e [credenciais](../src/api_sentinel/auth.py). Valores monetários e datas da massa são **sintéticos**, definidos pela [fixture](../data/fixtures/manual-sales.json).

Todos os dados são fictícios e produzidos localmente. A seed `20260101` gera duas organizações comerciais (Aurora, tenant 1; Horizonte, tenant 2), seis lojas (1–3 e 4–6, respectivamente), quarenta produtos `SKU-001` a `SKU-040` e sessenta dias completos, de 2026-01-01 a 2026-03-01. O tenant 3 e a loja 7 são exclusivamente técnicos, para o probe independente; cobrem somente 2026-01-01. Não são uma terceira organização comercial.

`python -m api_sentinel.cli seed --orders-per-day 30` é o volume padrão: 10.800 pedidos comerciais, com 1–3 itens por pedido. O gerador usa IDs estáveis derivados de loja, dia, posição do pedido e item, preços em centavos e PRNG local com seed fixa. O manifesto JSON registra algoritmo, parâmetros, contagem efetiva e SHA-256 de todas as linhas normalizadas. Ele fica em `/secrets/manifest.json`; o comando imprime o manifesto sem os tokens. A geração insere lotes de mil itens e não materializa a massa inteira.

O volume pode ser de 1 a 1.000 pedidos por loja/dia. Alterar volume sobre uma massa existente falha explicitamente; use outro volume de demonstração, nunca a massa de demonstração como banco de testes. Migração e seed têm credenciais administrativas separadas do papel de leitura da API. Uma trava transacional PostgreSQL serializa seeds concorrentes; uma segunda execução com os mesmos parâmetros preserva dados, tokens, expiração e revogação. O manifesto confere configuração e contagem; não é uma auditoria contra alterações diretas arbitrárias no banco. O papel de leitura e a ausência de endpoints de escrita sustentam a hipótese de imutabilidade da demo.

## Modelo e precisão

As [consultas](../src/api_sentinel/queries.py) implementam as fórmulas abaixo; a [fixture](../data/fixtures/manual-sales.json) permite recalculá-las independentemente.

- `tenants`: organização/tenant técnico e quota por segundo comum a todas as suas credenciais.
- `stores`: tenant, nome e cobertura de datas. A referência composta `(tenant_id, store_id)` impede associar um item a loja de outra organização.
- `products`: identificador, SKU único e nome fictício.
- `sale_items`: uma linha por item vendido, com `quantity`, `unit_price_cents`, `order_id` e `sold_at` com timezone.
- `datasets`: singleton com versão, instante de geração e manifesto da massa.
- `credentials`: somente hash SHA-256 do token aleatório, tenant, lojas autorizadas, escopos, expiração e revogação.

Receita em centavos = `SUM(quantity × unit_price_cents)`. Pedidos = `COUNT(DISTINCT (store_id, order_id))`; a chave inclui loja porque identificadores de pedido se repetem entre lojas. Ticket médio = receita/pedidos, arredondado para um centavo por `Decimal` com `ROUND_HALF_UP`. Não há ponto flutuante monetário. Uma loja com cobertura válida e nenhum pedido retorna receita/pedidos/ticket zero; período sem cobertura retorna erro `data_outside_coverage`, nunca um zero que simule informação conhecida.

`data/fixtures/manual-sales.json` contém um exemplo independente do gerador. Pedido `(7,101)`: duas unidades de 2.500 centavos e uma de 3.500 = 8.500. Pedido `(7,102)`: uma unidade de 4.000. Total 12.500 centavos, dois pedidos, ticket 6.250. Dois itens têm o mesmo instante, o que também testa o desempate da paginação. O primeiro item está exatamente no início do dia comercial; o último, um segundo antes do fim.

## Datas e respostas

Os [schemas](../src/api_sentinel/contracts.py) validam a entrada das [rotas](../src/api_sentinel/app.py); as [consultas](../src/api_sentinel/queries.py) aplicam a cobertura e o período solicitado.

`start` e `end` são datas inclusivas em `America/Sao_Paulo`, com 1–90 dias por consulta. O SQL usa intervalo UTC semiaberto: `[início de start, início de end+1)`. Por exemplo, 2026-01-01 corresponde a `[2026-01-01T03:00:00Z, 2026-01-02T03:00:00Z)`. Uma data sem timezone nunca é usada como instante de venda. A cobertura da loja precisa incluir todo o período pedido.

`GET /v1/stores` retorna `{items:[{id,name,coverage}]}`, filtrado pelo tenant e pela lista de lojas autorizadas. `GET /v1/stores/{id}/summary` retorna objeto direto com loja/período, `currency=BRL`, três indicadores monetários/contagem, `coverage`, `dataset_version`, `data_updated_at` e `observed_at`; o runtime acrescenta idade do cache. `data_updated_at` pertence à geração dos dados; `observed_at` ao cálculo. Um cache hit preserva ambos.

`GET /v1/stores/{id}/sales` pagina itens de venda, não pedidos inteiros: um pedido pode ocupar duas páginas. Cada item contém `id`, `order_id`, `sold_at`, `sku`, `quantity`, `unit_price_cents` e `line_total_cents`. Há no máximo 100 itens, `next_cursor` e metadados de cobertura/versão. O banco lê somente `limit+1`; nenhuma paginação em memória sobre a tabela completa.

## Cursor e versão

A implementação separa o [cursor](../src/api_sentinel/cursor.py), a [CLI de versão](../src/api_sentinel/cli.py) e o [modelo com seus índices](../src/api_sentinel/models.py).

A ordenação fixa é `(sold_at DESC, id DESC)`. O cursor codifica posição e vincula tenant, loja, período normalizado e versão da massa. É autenticado com HMAC-SHA-256 usando segredo local com pelo menos 32 caracteres; não contém SQL. Assinatura, tamanho máximo (2 KiB), tipos e campos são validados. Reutilização em outra loja/período/tenant ou após mudança de versão retorna `invalid_cursor`.

A massa é imutável durante a navegação. `python -m api_sentinel.cli advance-version` troca explicitamente a versão para demonstrar invalidação de cache e cursor; conserva os dados e `data_updated_at`. Não há snapshot garantido diante de alterações administrativas fora desse contrato. Um sistema com escrita real precisaria definir versão e invalidação transacionais ou aceitar um contrato de frescor diferente; não se promete consistência forte por TTL.

O índice composto `ix_sales_tenant_store_sold_id` alinha igualdade por tenant/loja, faixa por instante e desempate por ID. Colunas de receita/pedido estão incluídas para permitir um plano de leitura coberta quando as condições PostgreSQL permitirem. `python -m api_sentinel.cli explain` executa o SQL representativo com `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`, parâmetros vinculados e período limitado. O plano observado depende de volume, estatísticas e visibility map; não se promete uso de índice para toda consulta.

## Credenciais e ferramentas

Bearer é `sentinel_` seguido de 32 bytes aleatórios codificados como URL-safe base64 (256 bits de entropia). O projeto usa SHA-256 sem sal para esses tokens aleatórios; esta escolha local não é uma recomendação para armazenar senhas humanas. O [hash](../src/api_sentinel/auth.py) e a [emissão](../src/api_sentinel/cli.py) têm implementações separadas. O token não é registrado no banco nem nos logs. Cada requisição consulta expiração e revogação no banco, sem cache de credenciais entre réplicas.

`/secrets/demo.json`, fora do Git e com permissão restrita, guarda `tenant_a`, `tenant_b`, `probe`, `restricted` e `expired`. A credencial restricted só lista a loja 1; expired é emitida já expirada. Os escopos existentes são `stores:read`, `sales:read` (resumo e lista) e `inventory:read` (ERP). Todas as credenciais de um tenant herdam a mesma quota da tabela tenants.

A primeira gravação do JSON usa `0600`. O bootstrap local altera deliberadamente os arquivos para `0644`, permitindo leitura pelos diferentes usuários dos containers que montam o volume nomeado `secrets`; esse volume não é publicado como pasta HTTP nem versionado no Git. As atualizações atômicas preservam proprietário, grupo e permissões existentes. Assim, repetir `cli seed` como root não interrompe a leitura do probe por UID 10001. Essa escolha simplifica o laboratório local; a segregação de segredos por serviço é uma evolução necessária antes de exposição de produção.

Em tools com `DATABASE_URL` administrativo:

```sh
python -m api_sentinel.cli issue --tenant 1 --name leitura-loja-1 --stores 1 --scopes stores:read sales:read --expires-hours 24
python -m api_sentinel.cli revoke --name leitura-loja-1
python -m api_sentinel.cli advance-version
python -m api_sentinel.cli explain --tenant 1 --store 1 --start 2026-01-01 --end 2026-01-31
```

Emissão mostra o token apenas na saída explícita daquele comando; não copie essa saída para screenshots ou arquivos do repositório. Revogação por nome evita segredo no histórico de comandos. Seed funciona somente em `SENTINEL_ENV=demo` ou `test`; credenciais fictícias e papéis locais não são um arranjo de produção. Não há servidor OAuth próprio.

Os testes em `tests/integration/test_data_postgres.py` usam PostgreSQL real de teste com schemas temporários por caso; verificam fixture, limites de data, isolamento, escopos, revogação vista por dois pools independentes, paginação, alteração de versão, emissão e idempotência. Resultados executados ficam em `docs/verification.md`.
