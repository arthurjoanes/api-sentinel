# Consulta pelo proxy indisponível

Procedimento conferido em **22/09/2026**: [probe e fixture](../../alert_receiver/probe.py), [Compose](../../compose.yml) e [regras demo](../../monitoring/rules/demo.yml). Os comandos e prazos são instruções deste ambiente; não constituem nova medição de recuperação.

O probe é executado no receiver, com tenant técnico e credencial próprios. Ele exige HTTP 200, JSON válido e receita de 12.500 centavos, 2 pedidos e ticket médio de 6.250 centavos. A falha indica perda dessa jornada; sozinha, não identifica a causa.

## Confira primeiro

1. Abra a central de incidentes e leia condição, início e última atualização. Um receiver com probe desatualizado é falha de observação, não sinal de indisponibilidade atual.
2. No Grafana, compare sentinel_probe_success com o número de targets up do job api. Verifique também Redis, PostgreSQL, falhas de autenticação e rejeições de admissão.
3. Execute os comandos abaixo na raiz exclusiva do projeto; confirme o nome Compose pf-api-sentinel. Não pare outros projetos.

```powershell
docker compose -p pf-api-sentinel --profile observability ps
docker compose -p pf-api-sentinel logs --tail 80 proxy api receiver
docker compose -p pf-api-sentinel logs --tail 60 redis postgres
```

## Distinguir as causas

- Probe http_error e API sem targets: confira containers e descoberta DNS. Proxy pode retornar erro antes de chegar à API; esse erro não aparece no contador interno de requests.
- Probe http_error com API viva e Redis parado: quota falha fechada e responde 503. Restaurar somente cache não resolve a quota compartilhada.
- Probe contract: a API respondeu, mas schema, content type, tamanho ou totais não coincidiram com a fixture. Confira seed/versão e o contrato; não mude o resultado esperado para esconder o defeito.
- Probe configuration: não houve consulta. A disponibilidade é desconhecida, sentinel_probe_success fica NaN e sentinel_probe_config_valid fica 0. Confira os arquivos de segredo e réplicas esperadas; siga o runbook de telemetria, sem concluir indisponibilidade do negócio.
- Probe http_error com HTTP 401/403: confira expiração, revogação e escopo da credencial técnica. A falha da jornada técnica pode ocorrer enquanto credenciais comerciais ainda funcionam; use emissão/rotação pela CLI documentada sem imprimir tokens.
- Probe deadline com pool ocupado: siga os runbooks de saturação e latência; reiniciar tudo destrói os logs da causa.

## Recuperação

Interrompa somente o gerador de carga iniciado para este laboratório. Se o teste parou componentes, restaure os mesmos serviços. A API pode ter uma ou duas réplicas; mantenha a quantidade registrada no arquivo expected-replicas.

```powershell
docker compose -p pf-api-sentinel start redis postgres api
docker compose -p pf-api-sentinel --profile observability up -d proxy
```

Não execute down -v, prune global, exclusão de volume ou seed destrutivo como recuperação. Não amplie pools antes de recalcular o orçamento de conexões.

## Confirmar recuperação

Espere o probe validar novamente a fixture e o alerta receber resolved na mesma ocorrência. Confira ends_at e histórico em /api/incidents. Faça uma consulta comercial autorizada pelo proxy e observe erros/rejeições voltando ao normal. Se apenas a liveness voltou, a recuperação de negócio ainda não foi verificada.

## Limites

Aplicação e monitoramento param se o host cair.
