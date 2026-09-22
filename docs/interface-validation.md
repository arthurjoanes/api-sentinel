# Validação da interface — 22/09/2026

Adaptação sobre o commit `d03e3c5`. O registro [interface-review.json](evidence/interface-review.json) identifica os arquivos da primeira rodada por SHA-256. Essa rodada cobre a central, seus estados, navegação e renderização. O registro complementar [interface-package.json](evidence/interface-package.json) verifica a nova imagem, sem atribuir a ela uma nova prova de carga.

## O que mudou

A central abre a lista de todas as ocorrências, com filtros, estado, impacto e última observação. A consulta de referência ocupa uma faixa compacta e continua vencendo na tela sem atualizar os dados. O detalhe apresenta impacto, condição, ação recomendada e cronologia; entregas repetidas, firing atrasado e encerramento administrativo permanecem distinguíveis.

Runbooks têm catálogo em `/runbooks`, navegação por seções, listas semânticas e código escapado. Os destinos de Grafana, Jaeger e Prometheus conservam a resolução das URLs da mesma execução. A central não consulta métricas, quotas por cliente ou targets para preencher indicadores.

## Verificações realizadas

| Verificação | Resultado |
| --- | --- |
| Testes de UI, receiver, probe, retenção, erros, configuração e links | 134 testes e 9 subtests aprovados |
| Ruff nos arquivos Python envolvidos e módulo receiver | Aprovado; formato de 11 arquivos conferido |
| mypy no receiver | Aprovado; 8 arquivos de origem |
| Edge headless com Playwright | 12 telas/estados em 1440, 768, 640, 390 e 320 pixels de largura |
| Refluxo de conteúdo | Nenhuma rolagem horizontal da página inteira nos 60 recortes |
| Navegação e JavaScript | Link para pular ao conteúdo é o primeiro foco; link da observação abre seus detalhes; resultado recente vence; nenhum erro JavaScript |
| Inspeção visual | Central desktop/celular, detalhe, catálogo e procedimento examinados |

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

| Verificação na imagem | Resultado |
| --- | --- |
| Ruff global | Aprovado |
| Formato Python global | 70 arquivos conferidos |
| mypy nos alvos configurados pelo projeto | 27 arquivos aprovados |
| Testes de receiver, UI, probe, retenção, configuração e investigação | 134 testes e 9 subtests aprovados; 2 avisos de depreciação existentes |
| Comparação de `/app` com o workspace | 115 arquivos com SHA-256 correspondente; fontes da primeira rodada preservadas |
| Rotas HTTP em processo, com SQLite descartável e probe desativado | Central, health, CSS, JavaScript, catálogo e 7 runbooks com HTTP 200; slug desconhecido com HTTP 404 |
| Assets HTTP | Conteúdo servido idêntico aos bytes de CSS e JavaScript copiados para a imagem |
| Trivy no candidato | Nenhum achado nos pacotes Alpine, Python e binário Rust `uv`; zero HIGH/CRITICAL |

O registro complementar guarda os hashes dos 115 arquivos, os comandos, os resultados das rotas e o relatório resumido do scan. Distingue o índice OCI retornado por `docker image inspect` (`sha256:e4d6e0387af362bab25c7ca1e36b6a3301832fc640841ec30b2da9767e4b0945`) do manifesto Linux/amd64 (`sha256:e2de71b6e1034c6ac3739fdf17d831e2f0e083908610159536d447a8bb37a88a`) e da identidade reportada pelo Trivy.

O scan terminou em 22/09/2026 às 03:53:47 UTC e usa a imagem Trivy 0.74.0 fixada pelo CI, scanner `vuln`, `--ignorefile /dev/null`, análise de pacotes do sistema e das linguagens e bloqueio para qualquer achado HIGH/CRITICAL. A base foi atualizada às 02:00:05 UTC do mesmo dia, com próxima atualização prevista para 23/09/2026 às 02:00:05 UTC. O resultado e a identidade da base estão em `checks.vulnerability_scan` no JSON complementar. O Trivy avisou que Alpine 3.24 não constava em sua lista de fim de suporte; a análise de vulnerabilidades dos pacotes Alpine, Python e Rust foi executada.

O download inicial pelo espelho expirou. A tentativa no repositório oficial `ghcr.io/aquasecurity/trivy-db:2` sofreu uma falha de stream HTTP/2; a transferência foi concluída usando HTTP/1.1 com `GODEBUG=http2client=0`. Essa alteração de transporte manteve TLS, a mesma base oficial e o critério de aprovação. O relatório não constitui uma garantia de ausência de vulnerabilidades fora do escopo ou depois dessa data.

Os arquivos locais de reprodução e relatórios completos estão em `.runtime/interface-package/`, ignorados pelo Git: `check_package.py`, `package-files-routes.json`, `image-inspect.json`, `image-platform-inspect.json`, `runtime.json`, `trivy.log` e `record_evidence.py`. A base está em `.runtime/trivy-cache/`. Os comandos de lint, formato, tipos e testes também constam em `commands.checks` no registro versionado.

Esta rodada não iniciou a stack de observabilidade, não gerou carga nem entregas operacionais de alertas. `publication.json` foi preservado. Em `interface-review.json`, somente o nome da branch interna foi omitido; resultados, baseline e hashes das fontes permanecem iguais. Os hashes dos documentos atuais estão no registro complementar. Alterações posteriores desta documentação não mudam a imagem, pois `docs/*` é excluído do build, com exceção de `docs/runbooks/`.
