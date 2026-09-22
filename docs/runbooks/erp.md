# ERP simulado lento ou indisponível

Procedimento conferido em **22/09/2026**: [cliente ERP](../../src/api_sentinel/erp.py), [Compose](../../compose.yml) e [regras demo](../../monitoring/rules/demo.yml). Os comandos e prazos são instruções deste ambiente; não constituem nova medição de recuperação.

A integração é opcional e usa destino configurado, cliente HTTP reutilizado, limites de pool/concorrência, deadline total e circuito por processo. Resumos e vendas dependem de PostgreSQL e devem continuar funcionando sem ERP.

Execute os comandos na raiz do projeto, após o setup. O projeto Compose é `pf-api-sentinel`.

## Confira primeiro

Separe sentinel_erp_requests_total por resultado, duração, retries e circuito. Se apenas disponibilidade de SKU falha mas o resumo responde corretamente, o impacto não é indisponibilidade total. Verifique que o alerta está em severidade de atenção.

```promql
sum by (outcome) (rate(sentinel_erp_requests_total[2m]))
sentinel_erp_circuit_open
rate(sentinel_erp_retries_total[2m])
```

```powershell
docker compose -p pf-api-sentinel logs --tail 100 api erp
docker compose -p pf-api-sentinel ps erp
```

## Distinguir falhas

- Timeout/deadline: confira a latência do simulador e se o teste ativou resposta lenta ou fragmentada. Read timeout isolado não limita uma resposta que envia pequenos trechos continuamente.
- Contrato inválido: schema, content type ou bytes fora do limite não devem receber retry. Preserve o log e corrija o simulador/destino confiável.
- Saturação local do pool: reduza demanda; retry imediato aumenta a pressão.
- Circuito aberto: novas consultas falham rapidamente enquanto o probe de recuperação é controlado. O estado pertence a cada processo, portanto réplicas podem estar em fases diferentes.

## Recuperação

Remova a falha local usando o mesmo script que a ativou. Se o simulador foi parado, restaure somente esse serviço.

```powershell
docker compose -p pf-api-sentinel start erp
```

Não aponte o teste a terceiros ou metadata cloud e não aceite URL fornecida pelo cliente. Não desative verificação TLS nem limite de bytes para fazer a integração passar.

## Confirmar recuperação

Faça uma consulta autorizada de SKU conhecido, confirme schema/resultado e fechamento do circuito após chamada de recuperação. Em paralelo, valide resumo com números corretos. Aguarde a regra sair da condição e o receiver registrar resolved quando houver alerta ERP ativo.
