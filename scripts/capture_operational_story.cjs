/* Capture real, read-only checkpoints while review.py --scenario alerts --keep runs.
 * Start after its artifacts/problem-review/<UTC>/run.json is created, before alerts.
 * Usage: node scripts/capture_operational_story.cjs --run-dir <run-directory>
 *   --playwright-module <installed-playwright-module> --browser-executable <browser>
 * The supplied Playwright and browser versions are recorded; no package is installed.
 * Output stays in <run-directory>/operational-story. This does not inject alerts,
 * modify the DOM text, pause recovery, alter limits, or claim global availability.
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
const assert = require('node:assert/strict');
const { setTimeout: sleep } = require('node:timers/promises');

const args = {};
for (let i = 2; i < process.argv.length; i += 2) {
  const key = process.argv[i];
  assert(['--run-dir', '--playwright-module', '--browser-executable'].includes(key),
    'Unknown option: ' + key);
  assert(process.argv[i + 1], 'Missing option value');
  assert(!args[key], 'Duplicate option');
  args[key] = process.argv[i + 1];
}
for (const key of ['--run-dir', '--playwright-module', '--browser-executable']) {
  assert(args[key], 'Required: ' + key);
}
const runDir = fs.realpathSync(args['--run-dir']);
assert.equal(path.basename(path.dirname(runDir)), 'problem-review');
assert.equal(path.basename(path.dirname(path.dirname(runDir))), 'artifacts',
  'Run directory must be a direct child of artifacts/problem-review');
const runPath = path.join(runDir, 'run.json');
const output = path.join(runDir, 'operational-story');
fs.mkdirSync(output); // Never overwrite evidence from an earlier collector.
const hash = data => crypto.createHash('sha256').update(data).digest('hex');
const loadRun = () => {
  // The runner rewrites run.json. Tolerate only a short, incomplete-write window.
  for (let attempt = 0; attempt < 10; attempt++) {
    try { return JSON.parse(fs.readFileSync(runPath, 'utf8')); }
    catch (error) {
      if (!(error instanceof SyntaxError) && error.code !== 'ENOENT') throw error;
      if (attempt === 9) throw error;
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 50);
    }
  }
};
const firstRun = loadRun();
assert(/^pf-api-sentinel-review-[a-z0-9-]+$/.test(firstRun.project), 'Expected disposable project');
assert(firstRun.scenario === 'alerts', 'Expected bounded alerts scenario');
const deadline = Date.now() + 15 * 60 * 1000;
const manifest = {
  schema_version: 1,
  run_id: firstRun.id,
  project: firstRun.project,
  status: 'running',
  started_at: new Date().toISOString(),
  source_script: 'scripts/capture_operational_story.cjs',
  source_script_sha256: hash(fs.readFileSync(__filename)),
  capture_tool_scope: 'Collector runs outside the image and records its own hash; it may be newer than the copy in a frozen source archive.',
  viewport: { width: 1440, height: 1000 },
  method: 'Read-only live browser captures; synthetic commercial fixture, real local services and alert delivery. No DOM text replacement or artificial webhooks.',
  screenshots: [],
  browser_errors: [],
};
const save = () => fs.writeFileSync(path.join(output, 'capture.json'), JSON.stringify(manifest, null, 2) + '\n');
save();

async function request(base, route, json = true, token = undefined) {
  const url = new URL(route, base);
  assert(url.protocol === 'http:' && url.hostname === '127.0.0.1' && url.origin === new URL(base).origin,
    'Only this run loopback origin is allowed');
  const response = await fetch(url, { signal: AbortSignal.timeout(3000), redirect: 'error',
    headers: token ? { Authorization: 'Bearer ' + token } : {} });
  assert.equal(response.status, 200, 'Unexpected HTTP response for ' + route);
  const text = await response.text();
  assert(Buffer.byteLength(text) <= 1000000, 'Unexpectedly large response');
  return json ? JSON.parse(text) : text;
}

async function until(label, probe) {
  while (Date.now() < deadline) {
    const run = loadRun();
    assert.equal(run.id, firstRun.id, 'Run identity changed');
    assert.notEqual(run.status, 'failed', 'Operational runner failed; inspect its preserved evidence');
    const value = await probe(run);
    if (value) return value;
    await sleep(500);
  }
  throw new Error('Capture deadline exceeded: ' + label);
}

async function main() {
  const modulePath = fs.realpathSync(args['--playwright-module']);
  const { chromium } = require(modulePath);
  const packageInfo = JSON.parse(fs.readFileSync(path.join(modulePath, 'package.json'), 'utf8'));
  manifest.toolchain = { node: process.version, playwright_package: packageInfo.name, playwright_version: packageInfo.version };
  const browser = await chromium.launch({ headless: true, executablePath: args['--browser-executable'] });
  manifest.toolchain.browser_version = browser.version();
  const page = await browser.newPage({ viewport: manifest.viewport, locale: 'pt-BR', timezoneId: 'America/Sao_Paulo' });
  page.on('pageerror', error => manifest.browser_errors.push(error.message));
  try {
    const run = await until('HTTP checks completed', current => current.urls &&
      current.commands.some(c => c.name === 'http-tests' && c.exit_code === 0) && current);
    const base = run.urls.receiver;
    assert.equal(new URL(base).hostname, '127.0.0.1');
    manifest.receiver_origin = base;
    manifest.image_id = run.image_id;

    async function initialFixture() {
      const docker = (...command) => execFileSync('docker', command,
        { encoding: 'utf8', timeout: 10000, stdio: ['ignore', 'pipe', 'pipe'] }).trim();
      const ids = docker('ps', '-q', '--filter', 'label=com.docker.compose.project=' + run.project,
        '--filter', 'label=com.docker.compose.service=api').split(/\r?\n/).filter(Boolean);
      assert(ids.length >= 1 && ids.length <= 2, 'Expected own API containers');
      assert.equal(docker('inspect', '--format',
        '{{index .Config.Labels "com.docker.compose.project"}}', ids[0]), run.project);
      // Credential stays in process memory; neither command output nor token is persisted.
      const credentials = JSON.parse(docker('exec', ids[0], 'cat', '/secrets/demo.json'));
      assert(typeof credentials.probe === 'string' && credentials.probe.length >= 32);
      const fixture = await request(run.urls.proxy,
        '/v1/stores/7/summary?start=2026-01-01&end=2026-01-01', true, credentials.probe);
      assert.equal(fixture.store_id, 7);
      assert.equal(fixture.currency, 'BRL');
      assert.deepEqual([fixture.revenue_cents, fixture.order_count, fixture.average_ticket_cents],
        [12500, 2, 6250]);
      assert.equal(fixture.coverage.complete, true);
      return fixture;
    }

    async function capture(name, route, observations, assertVisible = async () => {}) {
      await assertVisible();
      const capturedAt = new Date().toISOString();
      const pngPath = path.join(output, name + '.png');
      const html = await page.content();
      fs.writeFileSync(path.join(output, name + '.html'), html);
      await page.screenshot({ path: pngPath, fullPage: true });
      await assertVisible();
      const proof = { captured_at: capturedAt, route, ...observations };
      const json = JSON.stringify(proof, null, 2) + '\n';
      fs.writeFileSync(path.join(output, name + '.json'), json);
      manifest.screenshots.push({ name, captured_at: capturedAt, route,
        png_sha256: hash(fs.readFileSync(pngPath)), html_sha256: hash(Buffer.from(html)),
        observations_sha256: hash(Buffer.from(json)) });
      save();
      console.log(JSON.stringify({ captured: name, run_id: run.id, at: capturedAt }));
    }

    const baselineIncidents = await request(base, '/api/incidents');
    const baselineIds = new Set(baselineIncidents.incidents.map(i => i.id));
    const initialObservations = { metrics: await request(base, '/metrics', false),
      fixture: await initialFixture(), incidents: baselineIncidents,
      scope: 'The fresh probe validated status, schema and expected amounts. This is not global health.' };
    await until('fresh validated fixture', async () => {
      const response = await page.goto(base + '/', { waitUntil: 'networkidle', timeout: 10000 });
      assert.equal(response.status(), 200);
      return (await page.locator('[data-observation-title]').textContent()) === 'Consulta de referência validada';
    });
    await page.locator('#observacao > summary').click();
    assert.equal((await page.locator('#observacao code').textContent()).trim(), 'success');
    assert.match(await page.locator('#observacao').textContent(), /R\$ 125,00 · 2 pedidos/);
    assert.equal(await page.locator('[data-observation-title]').textContent(), 'Consulta de referência validada');
    assert(Number(await page.locator('.observation').getAttribute('data-expires-in-ms')) > 0);
    await capture('01-fixture-validada', '/', initialObservations, async () => {
      assert.equal(await page.locator('[data-observation-title]').textContent(),
        'Consulta de referência validada', 'Probe expired during screenshot');
    });

    const firing = await until('SentinelUnavailable firing', async () => {
      const items = (await request(base, '/api/incidents')).incidents;
      return items.find(i => !baselineIds.has(i.id) &&
        i.labels.alertname === 'SentinelUnavailable' && i.status === 'firing');
    });
    const identity = { id: firing.id, fingerprint: firing.fingerprint, starts_at: firing.starts_at };
    manifest.incident_identity = identity;
    const detail = '/incidents/' + firing.id;
    await page.goto(base + detail + '?status=firing', { waitUntil: 'networkidle', timeout: 10000 });
    assert.equal((await page.locator('.detail-labels .badge').textContent()).trim(), 'Em andamento',
      'Incident changed before capture; do not substitute a synthetic screen');
    assert.equal((await page.locator('h1').textContent()).trim(), 'Consulta pelo proxy indisponível');
    for (const title of ['Datas e entregas', 'Identidade da ocorrência']) {
      await page.locator('summary').filter({ hasText: title }).click();
    }
    const firingProof = await request(base, '/api/incidents/' + firing.id);
    assert.equal(firingProof.incident.status, 'firing');
    assert(!firingProof.events.some(event => event.transition === 'recovered'));
    await capture('02-incidente-ativo', detail + '?status=firing', firingProof);

    await until('same incident resolved', async () => {
      const result = await request(base, '/api/incidents/' + firing.id);
      return result.incident.status === 'resolved' && result;
    });
    await page.goto(base + detail + '?status=resolved', { waitUntil: 'networkidle', timeout: 10000 });
    assert.equal((await page.locator('.detail-labels .badge').textContent()).trim(), 'Resolvido');
    assert.equal(await page.locator('.reconciliation').count(), 0, 'Manual closure is not recovery');
    for (const title of ['Datas e entregas', 'Identidade da ocorrência']) {
      await page.locator('summary').filter({ hasText: title }).click();
    }
    const resolvedProof = await request(base, '/api/incidents/' + firing.id);
    for (const key of Object.keys(identity)) assert.equal(resolvedProof.incident[key], identity[key]);
    assert(resolvedProof.incident.ends_at && resolvedProof.incident.deliveries >= 2);
    assert(resolvedProof.events.some(event => event.delivered_status === 'resolved' &&
      event.transition === 'recovered'), 'Recovery webhook missing from history');
    assert(!resolvedProof.events.some(event => event.transition === 'operator_reconciled'));
    await capture('03-mesma-ocorrencia-recuperada', detail + '?status=resolved', resolvedProof);
    assert.equal(manifest.browser_errors.length, 0);
    manifest.status = 'passed';
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  manifest.status = 'failed';
  manifest.failure = { name: error.name, message: error.message };
  console.error(error.message);
  process.exitCode = 1;
}).finally(() => {
  manifest.finished_at = new Date().toISOString();
  save();
});
