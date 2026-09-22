# Segurança da demonstração local

Os controles estão no [Compose](../compose.yml), na [autorização](../src/api_sentinel/auth.py), no [cliente ERP](../src/api_sentinel/erp.py) e na [ACL Redis](../deploy/redis/users.acl). Scans e testes são observações das imagens, datas e bases identificadas em cada recibo.

Os serviços publicados usam `127.0.0.1`. A demonstração pressupõe controle do host e dos volumes Docker; não é uma implantação compartilhada ou exposta à Internet. Os dados comerciais e as credenciais PostgreSQL de demonstração são locais e identificados como tal no Compose.

## API e Redis

A autorização por organização, loja e escopo ocorre antes de ler o cache. O cursor autenticado vincula organização, loja, período e versão dos dados. Limites de entrada, admissão, consulta e resposta restringem o trabalho em andamento; a integração ERP usa destino fixo e não segue redirecionamentos.

O primeiro início gera credenciais Redis aleatórias em volumes próprios, fora do Git. Repetir o início preserva essas credenciais. O usuário `default` fica desabilitado; cache e quota usam usuários separados, com comandos e padrões de chave restritos. O healthcheck tem acesso a `PING`. A administração usada pelos experimentos fica em um volume montado somente no serviço operacional `tools`.

Os testes com Redis real verificam rejeição de conexão anônima e impedem que os usuários da aplicação executem administração ou acessem as chaves do outro usuário. A suíte também verifica quota compartilhada e prevenção de cálculos simultâneos da mesma chave. Os experimentos de indisponibilidade usam o acesso administrativo sem colocar senhas nos argumentos dos processos ou nos relatórios.

## Grafana

O painel é anônimo com papel `Viewer`. A autenticação por senha está desabilitada, não é criado administrador inicial e Gravatar está desabilitado. A versão 12.4.11 tem digest fixado no [Compose](../compose.yml). O aviso oficial **CVE-2026-76154**, publicado em **17/09/2026** e consultado em **22/09/2026**, lista 12.4.11 entre as versões corrigidas para esse problema específico; isso não comprova correção de todas as vulnerabilidades da linha. Referências: [autenticação Grafana](https://grafana.com/docs/grafana/latest/setup-grafana/configure-access/configure-authentication/grafana/) e [aviso de segurança corrigido em 12.4.11](https://grafana.com/security/security-advisories/cve-2026-76154/).

Os testes HTTP confirmam que o dashboard provisionado continua legível, sem permissão de edição ou administração, que a credencial inicial pública não acessa a API administrativa e que o endpoint de login por senha está desativado. Ocultar o formulário, isoladamente, não impedia esse acesso na configuração anterior.

Atualizar a configuração não apaga usuários, sessões ou dashboards de um volume Grafana existente. Os ensaios usam volumes novos; nenhum volume de demonstração anterior é removido pelo verificador.

## Verificação e limites

Na revisão de 22/09/2026, o [scan da execução completa](evidence/editorial-20260922/full-vulnerabilities.json) e o [scan da imagem final das capturas](evidence/editorial-20260922/capture-vulnerabilities.json) reportaram zero vulnerabilidades no escopo da aplicação. Trivy 0.74.0 examinou sistema, Python e binário Rust, sem exclusões ou filtro de severidade. As imagens são diferentes e estão identificadas em cada registro; nenhuma delas representa um scan dos serviços auxiliares. O aviso de ausência da data de fim de suporte do Alpine 3.24 na lista interna do scanner permanece registrado.

Gitleaks 8.30.1 examinou os 12 commits alcançáveis e a cópia dos arquivos rastreados/novos publicáveis. A primeira leitura da nova evidência encontrou 12 checksums de fontes e um nome de fixture sintética. Recalculei os quatro SHA-256 e conferi o rótulo, sem confundi-los com valores de credenciais. A política passou a reconhecer apenas esses valores literais nos três caminhos exatos dos relatórios, e o nome exato em um deles. O scan seguinte passou; um token fictício no mesmo caminho continuou sendo detectado no controle positivo. [Escopo, triagem e controle](evidence/editorial-20260922/secret-review.json).

O workflow de segredos examina o histórico Git. As exceções de Gitleaks identificam fingerprints de arquivos e rótulos de credenciais sintéticas, sem excluir diretórios completos. Tokens, senhas e arquivos de execução permanecem fora do repositório.

O scan Trivy do CI cobre a imagem Python da aplicação, incluindo seus pacotes de sistema e bibliotecas. Ele bloqueia achados `HIGH` e `CRITICAL`, mesmo quando ainda não há correção disponível. Esse resultado não representa uma varredura de todas as imagens PostgreSQL, Redis, proxy, observabilidade e geração de carga. As versões e o escopo dos ensaios constam em [verificação](verification.md).

O runtime inclui as ferramentas necessárias aos testes e relatórios locais. Antes de uma implantação de produção, a imagem de serviço e as ferramentas operacionais precisam de ciclos de entrega separados; a demonstração não oferece essa implantação.
