# Documentação do projeto

O README apresenta a aplicação, a conta de referência, a arquitetura e o comando de execução. Os guias detalham uso, contratos e operação. Informações extensas ficam em expansões ou páginas próprias, com links relativos estáveis.

## Onde documentar

| Assunto | Guia |
| --- | --- |
| Uso da central e significado dos registros | [Central de incidentes](incident-console.md) |
| Instalação, demonstração e limpeza | [Roteiro operacional](demo.md) |
| Componentes e limites | [Arquitetura](architecture.md) e [contrato de dados](data-contract.md) |
| Testes, desempenho e segurança | [Verificação](verification.md), [desempenho](performance.md) e [segurança](security.md) |
| Fontes de afirmações e resultados | [Registro de fontes](fontes-e-afirmacoes.md) |

## Exemplos e imagens

Identifique dados sintéticos e sua fixture. Mantenha unidades explícitas: centavos nos contratos financeiros, UTC nos horários e a unidade correspondente nos gráficos. Uma imagem de interface apresenta um estado; cálculo, isolamento e recuperação exigem registros próprios da execução.

A [galeria](screenshots.md) mostra a central e o detalhe. Imagens novas não alteram as datas ou o alcance de resultados históricos. Preserve os registros técnicos originais e informe cenário, comando, ambiente e data ao citar uma execução.

A marca usa azul sentinela `#14334B` para estrutura, azul de ação `#155BA6` para links, petróleo `#087F8C` para contexto e gelo `#F0F5F8` nas superfícies. Texto usa `#1B2E40` e metadados `#4C6374`. Cores de estado acompanham rótulos; petróleo não representa saúde do serviço. Os selos locais são atalhos de navegação, sem afirmar aprovação automática.

<a id="afirmações-fontes-e-datas"></a>

## Fontes e manutenção

Ligue limites e versões ao código ou à configuração. Para resultados técnicos, informe data, identidade da execução, unidade e denominador; uma aprovação não se transfere a outro commit. Use fontes primárias para informações externas e registre a data quando ela afetar a interpretação.

Blocos de código declaram a linguagem, como `python`, `json`, `sql`, `yaml`, `sh` ou `powershell`. Preserve comandos reproduzíveis e confira links, âncoras, exemplos e licenças ao atualizar os guias. Diagramas têm explicação textual e ligação à implementação; o README conserva o Mermaid completo junto ao mapa compacto.
