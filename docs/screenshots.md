# Recortes da interface atual

O [manifesto de captura](screenshots/focused-20260922/capture.json) e o [coletor](../scripts/capture_docs.cjs) documentam a origem das imagens. A data da captura identifica o layout fotografado, sem atualizar a data dos incidentes exibidos.

Capturados em **22/09/2026, 17:37 UTC**, diretamente no navegador, sem montagem ou alteração dos dados. Cada imagem isola o trecho relacionado à explicação; páginas históricas completas ficam disponíveis por links.

A fila usa registros preservados do receiver local. Os recortes mostram filtros e ocorrências, ou o histórico recebido; não abriram alertas nem executaram falha/recuperação.

| Foco                            | Imagem                                                            |
| ------------------------------- | ----------------------------------------------------------------- |
| Filtros e duas ocorrências      | [Abrir recorte](screenshots/focused-20260922/fila-foco.png)       |
| Fila no celular, uma ocorrência | [Abrir recorte](screenshots/focused-20260922/fila-movel-foco.png) |
| Duas entregas no histórico      | [Abrir recorte](screenshots/focused-20260922/historico-foco.png)  |

O [manifesto](screenshots/focused-20260922/capture.json) registra rotas, viewport, coordenadas do recorte, seletores, fontes, código e hashes. Fontes carregadas, ausência de erros JavaScript e reflow foram conferidos. Os recortes desktop têm altura/largura de no máximo 1,1; os móveis têm altura inferior a 650 px. A captura usa `clip` a partir dos limites reais dos elementos, sem reduzir um print longo para caber na documentação.

## Reproduzir

Requer Node.js, Playwright e Chromium/Edge. Defina `PLAYWRIGHT_MODULE` com o caminho absoluto do módulo e `PLAYWRIGHT_CHANNEL=msedge` para usar Edge. Inicie o receiver local antes da captura. O script navega por cinco rotas em 1120, 390 e 320 px, mas salva apenas os três recortes úteis abaixo.

```sh
node scripts/capture_docs.cjs http://127.0.0.1:9184 .runtime/docs-captures/novo-recorte
```

Escolha uma saída nova: o script recusa sobrescrever imagens. Confira região, legibilidade e datas antes de promover outro recorte à README. O histórico não é substituído por capturas novas: seus manifests e pixels permanecem com a execução original.

## Conservação e limpeza

Capturas com hashes e pares de comparação continuam ligados às execuções originais. O inventário da limpeza e as cópias de segurança anteriores ficaram fora do repositório; não são uma prova pública de contagem de arquivos removidos. Para a proveniência das imagens publicadas, use o manifesto ligado acima, de **22/09/2026**.
