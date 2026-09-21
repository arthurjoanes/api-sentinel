# Consultar lojas quando uma dependência degrada

## Problema e tese

Integrações e operadores de uma rede de lojas precisam consultar vendas e disponibilidade sem misturar clientes, inventar totais ou bloquear toda a API quando o ERP fica lento. É um problema plausível; não houve entrevista, piloto com cliente ou operação em produção.

A alternativa simples é uma API que consulta PostgreSQL/ERP diretamente, com retry manual e um contador de erros. Ela basta para pouca concorrência sem falhas. A restrição demonstrável aqui é manter consultas de vendas corretas enquanto chamadas ERP ocupam tempo/conexões, e recusar pressão excedente sem retirar a quota compartilhada quando Redis falha.

A tese é contenção e recuperação verificáveis: identidade deriva da credencial, autorização antecede cache/ERP, concorrência tem limite imediato, quota é compartilhada, ERP tem prazo/circuito e o probe independente acompanha uma fixture. Duas réplicas locais não demonstram escala geográfica nem SLO mensal.

## Diagnóstico

Jornada pequena, sem carga/falha: `artifacts/problem-review/baseline-http.json`. Lojas A retornaram apenas 1–3; fixture retornou 12.500 centavos/2 pedidos/ticket 6.250; A acessando loja 4 recebeu 403; ERP local respondeu identificação correta. Isso mostra os cinco casos básicos, não substitui a matriz operacional.

| Alegação / situação | Implementação existente | Resultado na época e classificação | Lacuna | Correção planejada | Critério anterior à medição |
|---|---|---|---|---|---|
| Consulta correta e isolada | auth → quota → admissão → cache/SQL; fixture manual | 5 leituras reais; parcial | carga anterior confere status, não o resultado | conferência independente por linhas brutas e validação em cada 200, mistura de rotas/clientes | zero divergência de identidade, escopo, moeda, receita, pedidos e itens |
| ERP degradado preserva vendas | bulkhead 4, deadline 900 ms e circuito local | código e teste antigo; parcial | falha sequencial não demonstra mistura simultânea | carga aberta com ERP lento e consultas comerciais concorrentes | vendas normais sem falha, ERP limitado, nenhum drop; recuperação com resposta conhecida |
| Redis inteiro falha fechado; só cache permite fallback | clientes/ACL separados; quota Lua | código e teste antigo; parcial | roteiro altera a massa/stack demo | stack operacional descartável, mesma configuração funcional e volumes próprios | 503 quota_unavailable, live 200, zero consulta SQL de resumo durante queda; depois 200 correto |
| Quota não duplica com réplicas | janela Redis comum por tenant | teste antigo; parcial | denominador do cliente quente incompleto e rota única | contagem de todas as conclusões/rejeições e mesmos parâmetros em 1/2 réplicas | quota observada em ambos, zero erro inesperado, sem ganho aparente por rejeição |
| Cache evita stampede | lock distribuído com token/TTL | teste antigo; parcial | relatório registra 1/0/1 sem afirmar o resultado | asserção sobre SQL e igualdade dos resultados antes/depois | quatro chamadas/fase, 1/0/1 consultas de resumo; zero valor incorreto |
| Alerta chega e resolve sem depender da API | probe → Prometheus → AM → receiver SQLite | teste antigo; parcial | demonstração para serviços da stack persistente | ciclo real apenas no projeto descartável | firing/resolved em até 90 s cada, mesma ocorrência; todos incidentes novos resolvidos e probe correto |
| Medição reproduzível sem perder falhas | JSON por nome fixo | parcial | sobrescreve execução e pode tratar alguns 200 como sucesso suficiente | diretório UTC por execução, fingerprint, exit code, limiares, inventário e registro de falhas | arquivos preservados, denominadores completos e resultado não aprovado se houver drop/erro/contrato incorreto |
| Operador investiga o ambiente do incidente | links em portas fixas da demo | defeito confirmado ao ler UI e executar stack com portas próprias | Grafana/Jaeger de outra stack podem parecer o ambiente do incidente | resolver destinos por arquivo local validado da execução | quatro redirects 307 para as portas efetivas; arquivo inválido retorna 503 sem fallback |

## O que a execução revelou

Duas execuções passaram na mistura normal, ERP degradado e recuperação, com conteúdo validado, e falharam na carga de quota: 300 resultados corretos, 299 respostas 429 e duas respostas 503 em 601 conclusões. Não houve drop ou conteúdo incorreto.

A primeira hipótese era a ausência de aquecimento após mudar a quantidade de réplicas. A segunda execução a refutou: houve a mesma falha com uma réplica já aquecida. Os contadores localizaram exatamente duas rejeições em `auth`; não demonstraram a causa subjacente da espera. A admissão de autenticação foi ajustada de quatro para oito operações, mantendo pool de 2, aquisição de 200 ms e prazo de 500 ms. O teste concorrente exige recusa da nona sem iniciar autenticação adicional e verifica liberação após cancelamento. A [execução final](../artifacts/problem-review/20260921t064944662185z/summary.json) passou sem mudar a taxa nem relaxar os limiares; isso não garante o resultado sob qualquer carga.

| Critério final | Resultado | Situação |
|---|---|---|
| Conteúdo e escopo sob mistura | 151/151 normais; 70 testes HTTP; cada 200 validado contra linhas brutas | Executado localmente |
| ERP isolado e recuperado | 114 consultas comerciais corretas, 37 falhas só ERP; depois 101/101 corretas | Executado localmente |
| Quota e outro tenant | 300 corretas +301 quota em 1 e 2 réplicas; B51/51 sob A60/s | Executado localmente |
| Cache/Redis e recuperação | SQL1/0/1; Redis parado: live200, ready503, negócio503 e SQL0; retorno correto | Executado localmente |
| Alerta e retorno conhecido | Dois ciclos firing/resolved, mesma ocorrência, sete incidentes finais resolvidos e fixture correta | Executado localmente |
| Registros preservados | Diretórios separados, falhas mantidas, 81 arquivos sem segredos conhecidos da execução | Executado; guardas de limpeza também testadas sem Docker |
| Utilidade e disponibilidade externa | Nenhum piloto, serviço externo real ou janela de 30 dias | Não demonstrado |

O problema dos links foi reproduzido e corrigido: quatro destinos retornaram 307 para portas da stack descartável, e o HTML atual contém navegação relativa. Testes cobrem configuração ausente/inválida, destinos externos e serviço desconhecido. A aparência da central não foi redesenhada.

## Experimento que pode refutar a tese

Sob oferta pequena pré-definida, um ERP lento que cause erro nas consultas independentes, uma resposta 200 de tenant errado, um Redis indisponível que libere SQL protegido, ou recuperação sem voltar à fixture conhecida reprova a tese. Não basta reduzir p95 global com 503 rápidos. Carga normal/ERP lenta usa o mesmo gerador, período e mistura; só a condição da dependência muda. O teste compara comportamento de falha, não promete benefício comercial.

## Limites e fontes

Integração real local com PostgreSQL, Redis, NGINX e ERP simulado; sem fornecedor externo ou custo. Utilidade com operadores reais permanece não avaliada. Fontes oficiais conferidas em 21/09/2026: [Compose merge](https://docs.docker.com/reference/compose-file/merge/) para portas/volumes isolados; [k6 arrival rate](https://grafana.com/docs/k6/latest/using-k6/scenarios/concepts/arrival-rate-vu-allocation/) para distinguir chegadas e drops; [HTTPX timeouts](https://www.python-httpx.org/advanced/timeouts/) para limites de leitura/pool. Elas orientam o método, não os resultados.
