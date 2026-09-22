# Reprodução da revisão

Estes helpers executam cenários sintéticos isolados. Não iniciam PostgreSQL, Redis,
Prometheus ou carga, nem acessam o banco da demonstração. `preview.py` usa somente
`/tmp/review/alerts.db` no container descartável e gera a credencial efêmera localmente.
Os arquivos do baseline vêm do commit, sem alterações. O banco é recriado em cada
inicialização desse preview.

Na raiz do repositório, prepare `.runtime/quality/` copiando os helpers deste
diretório. Exporte com UTF-8 os bytes de `git show be419e0:alert_receiver/ui.py`,
`styles.css` e `snapshot.js` para `baseline_ui.py`, `baseline.css` e `baseline.js`
nesse diretório. O fixture será compartilhado por baseline e candidato.

```sh
docker build -t pf-api-sentinel-quality:20260922 .
docker run --rm --name ui-api-quality-preview --read-only --tmpfs /tmp \
  --cap-drop ALL --security-opt no-new-privileges \
  -p 127.0.0.1:9816:8000 \
  -v "$PWD:/app:ro" -v "$PWD/.runtime/quality:/review:ro" \
  -e PYTHONPATH=/app:/app/src:/review -w /app \
  pf-api-sentinel-quality:20260922 uvicorn preview:app --host 0.0.0.0 --port 8000
```

Com Playwright Test e Edge instalados, use `PLAYWRIGHT_MODULE` para indicar o módulo
caso ele não esteja no caminho padrão do Node. Nenhum pacote foi adicionado à aplicação.

```sh
node .runtime/quality/candidate-review.cjs
node .runtime/quality/compare.cjs
node .runtime/quality/visual-audit.cjs
node .runtime/quality/extended-review.cjs
node .runtime/quality/disclosure-review.cjs
```

Os relatórios de browser usam a fonte montada para revisão. O comando abaixo,
separado, confere lint, formato, tipos, testes unitários, rotas e hashes de `/app`
**copiados para a imagem**, montando somente o helper de inspeção:

```sh
docker run --rm --name ui-api-quality-package --network none --read-only \
  --tmpfs /tmp:rw,nosuid,size=384m --cap-drop ALL \
  --security-opt no-new-privileges \
  -v "$PWD/.runtime/quality/check_candidate.py:/review/check_candidate.py:ro" \
  pf-api-sentinel-quality:20260922 python /review/check_candidate.py
```

Três testes de leitura por UID exigem Linux/root; reproduza somente esses em outro
container descartável com `--user 0 --cap-drop ALL --cap-add CHOWN --cap-add SETUID
--cap-add DAC_OVERRIDE`, rede desligada e `/tmp` temporário. Alvo:
`tests/unit/test_data_private_file.py::test_seed_rewrite_preserves_owner_permissions_and_reader_access`.
Isso não muda o usuário da aplicação nem suas capabilities em produção.

O [registro do pacote](../package.json) guarda comandos, identidades da imagem,
validade da base Trivy, resultados e hashes. O scanner usa a imagem 0.74.0 fixada
pelo CI, Docker socket local e base previamente obtida, com `--network none`,
`--skip-db-update --skip-java-db-update --offline-scan --scanners vuln
--ignorefile /dev/null`. Reutilizar a base só é válido antes de `NextUpdate`; fora
dessa janela, obtenha a base atual. O gate rejeita qualquer HIGH/CRITICAL.

Ao terminar, encerre somente `ui-api-quality-preview`. O preview não tem volume
persistente. Capturas comprovam apresentação; os testes e checks comprovam apenas
os cenários explicitados nos respectivos relatórios.
