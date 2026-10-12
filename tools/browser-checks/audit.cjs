'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');

const args = {};
for (let index = 2; index < process.argv.length; index += 2) {
  const key = process.argv[index];
  assert(['--server-info', '--output', '--playwright-module', '--browser-executable', '--mode', '--engine', '--axe-module'].includes(key), 'Unknown option');
  assert(process.argv[index + 1] && !args[key], 'Missing or repeated option');
  args[key] = process.argv[index + 1];
}
assert(args['--server-info'] && args['--output'], 'Provide --server-info and a new --output directory');
assert(['capture', 'audit'].includes(args['--mode'] || 'capture'), 'Use capture or audit mode');
assert(['chromium', 'firefox', 'webkit'].includes(args['--engine'] || 'chromium'), 'Use a named browser engine');
const info = JSON.parse(fs.readFileSync(args['--server-info'], 'utf8'));
const origin = new URL(info.url);
assert(origin.protocol === 'http:' && origin.hostname === '127.0.0.1' && !origin.username && !origin.password, 'Use the isolated loopback fixture');
assert(info.synthetic && info.readonly_http && info.status === 'ready', 'Fixture server must be ready');
const output = path.resolve(args['--output']);
assert(!fs.existsSync(output), 'Use a new directory to preserve previous evidence');
fs.mkdirSync(output, {recursive: true});
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const sorted = value => JSON.stringify(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)));
const fingerprint = () => Object.fromEntries(Object.keys(info.source_files_sha256_before).sort().map(relative => [relative, sha(fs.readFileSync(path.join(info.source, relative)))]));
const before = fingerprint();
assert.equal(sorted(before), sorted(info.source_files_sha256_before), 'Fixture source differs from its startup identity');
const fixturePath = path.join(path.dirname(path.resolve(args['--server-info'])), 'private', 'alerts.sqlite3');
const fixtureBefore = sha(fs.readFileSync(fixturePath));
const serverHelperPath = path.join(__dirname, 'server.py');
const serverHelperBefore = sha(fs.readFileSync(serverHelperPath));
const modulePath = args['--playwright-module'] || process.env.PLAYWRIGHT_MODULE || '@playwright/test';
const playwright = require(modulePath);
const moduleInfo = require(path.join(path.dirname(require.resolve(modulePath)), 'package.json'));
const record = {
  schema_version: 1,
  started_at: new Date().toISOString(),
  mode: args['--mode'] || 'capture',
  synthetic: true,
  source_commit: info.source_commit,
  fixture_time: info.fixture_time,
  engine: args['--engine'] || 'chromium',
  node: process.version,
  playwright_version: moduleInfo.version,
  tool_sha256: sha(fs.readFileSync(__filename)),
  server_helper_sha256: serverHelperBefore,
  context_fixture_sha256_before: fixtureBefore,
  source_files_sha256_before: before,
  views: [], images: [], page_errors: [], checks: [], accessibility: [], journeys: [],
  scope: 'Synthetic isolated receiver; presentation and navigation only; no stack availability claim',
};
fs.copyFileSync(__filename, path.join(output, 'capture-tool.cjs'));
fs.copyFileSync(serverHelperPath, path.join(output, 'fixture-server.py'));

function check(name, passed, facts = {}) {
  record.checks.push({name, passed: Boolean(passed), ...facts});
}

async function auditUI(page, context, browser) {
  const {expect} = playwright;
  const axePath = args['--axe-module'] || '@axe-core/playwright';
  const axePackage = require(axePath);
  const AxeBuilder = axePackage.default || axePackage.AxeBuilder;
  record.axe_version = '4.13.0';
  const widths = [320, 390, 768, 1024, 1440];
  const routes = [
    ['central', '/', 200], ['firing', '/?status=firing', 200], ['resolved', '/?status=resolved', 200],
    ['firing-detail', '/incidents/1?status=firing', 200],
    ['recovered-detail', '/incidents/2?status=resolved', 200],
    ['manual-detail', '/incidents/3?status=resolved', 200],
    ['runbooks', '/runbooks', 200], ['runbook-context', '/runbooks/erp?incident_id=1&status=firing', 200],
    ['missing-tools', '/tools/jaeger/', 503], ['empty', '/__review/empty', 200],
    ['no-active', '/__review/no-active', 200], ['stale', '/__review/stale', 200],
    ['disabled', '/__review/disabled', 200], ['probe-failure', '/__review/failure', 200],
    ['read-failure', '/__review/error', 503], ['long', '/__review/long', 200],
    ['volume', '/__review/volume', 200], ['no-sli', '/__review/no-sli', 200],
    ['expired-trace-fixture', '/__review/expired-trace', 410],
  ];
  record.audit_widths = widths;
  record.fixture_scope = {
    no_sli: 'Unavailable observation fixture; does not calculate an SLI',
    expired_trace: 'Explicit 410 presentation fixture; does not prove Jaeger retention',
    timer: 'Date-only epoch offset aligned to the fixed fixture and progressing with native elapsed time; native timers, Navigation Timing and performance; real network/script delay and history navigation; explicitly simulated wall time',
  };
  for (const width of widths) {
    await page.setViewportSize({width, height: 1000});
    for (const [name, route, status] of routes) {
      const response = await page.goto(new URL(route, origin).href);
      check('route-status', response?.status() === status, {name, route, width});
      await page.evaluate(() => document.fonts.ready);
      const state = await page.evaluate(() => ({
        content_width: document.documentElement.scrollWidth,
        viewport: innerWidth, headings: document.querySelectorAll('h1').length,
        fonts_loaded: [...document.fonts].every(font => font.status === 'loaded'),
        inline_scripts: document.querySelectorAll('script:not([src])').length,
      }));
      check('reflow-and-fonts', state.content_width <= width && state.fonts_loaded && state.headings === 1, {name, route, width, ...state});
      check('no-inline-script-injection', state.inline_scripts === 0, {name, route, width});
      const policy = response.headers()['content-security-policy'] || '';
      check('production-csp', policy.includes("default-src 'none'") && policy.includes("script-src 'self'") && !policy.includes('unsafe-inline') && !policy.includes('unsafe-eval'), {name, route, width});
      const result = await new AxeBuilder({page}).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
      record.accessibility.push({name, route, width, violations: result.violations.map(item => ({id: item.id, impact: item.impact, tags: item.tags, targets: item.nodes.map(node => node.target)})), manual_review: result.incomplete.map(item => ({id: item.id, targets: item.nodes.map(node => node.target)}))});
      check('axe-no-violations', result.violations.length === 0, {name, route, width, violations: result.violations.length});
    }
    for (const status of ['all', 'firing', 'resolved']) {
      let stage = 'filter';
      try {
        await page.goto(new URL(`/?status=${status}`, origin).href);
        await expect(page.locator('nav[aria-label="Filtrar incidentes"] [aria-current="page"]')).toHaveAttribute('href', `/?status=${status}`);
        const incident = page.locator('a[href^="/incidents/"]').first();
        const destination = await incident.getAttribute('href');
        const id = destination.match(/incidents\/(\d+)/)[1];
        stage = 'keyboard-detail';
        await incident.focus(); await page.keyboard.press('Enter');
        await expect(page).toHaveURL(new URL(destination, origin).href);
        const back = page.locator(`a[href="/?status=${status}#incidente-${id}"]`);
        await expect(back).toHaveCount(1);
        stage = 'keyboard-runbook';
        const runbook = page.locator('main a[href^="/runbooks/"]').first();
        await runbook.focus(); await page.keyboard.press('Enter');
        const section = page.locator('main a[href^="#"]').first();
        const sectionId = (await section.getAttribute('href')).slice(1);
        await section.focus(); await page.keyboard.press('Enter');
        await expect(page.locator(`#${sectionId}`)).toBeFocused();
        stage = 'return-detail-and-filter';
        await page.locator(`a[href="${destination}"]`).first().click();
        await page.locator(`a[href="/?status=${status}#incidente-${id}"]`).click();
        await expect(page.locator(`#incidente-${id}`)).toBeFocused();
        await expect(page.locator('nav[aria-label="Filtrar incidentes"] [aria-current="page"]')).toHaveAttribute('href', `/?status=${status}`);
        stage = 'native-back';
        await page.goBack();
        await expect(page).toHaveURL(new URL(destination, origin).href);
        record.journeys.push({width, status, passed: true, keyboard_detail_runbook_return: true, row_focus: true, native_back: true});
      } catch (error) {
        record.journeys.push({width, status, passed: false, stage, error_type: error.name});
      }
    }
    await page.goto(new URL('/runbooks/erp?incident_id=1&status=firing', origin).href);
    const codeSupport = await page.evaluate(() => {
      const rgb = value => value.match(/[\d.]+/g)?.map(Number);
      const luminance = value => {
        const c = rgb(value).slice(0, 3).map(v => v / 255).map(v => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
        return c[0] * 0.2126 + c[1] * 0.7152 + c[2] * 0.0722;
      };
      const seen = new Set();
      const contrast = [];
      for (const element of document.querySelectorAll('.code-block code, .code-block [class^="syntax-"]')) {
        if (seen.has(element.className)) continue;
        seen.add(element.className);
        let background = element;
        while (background && rgb(getComputedStyle(background).backgroundColor)?.[3] === 0) background = background.parentElement;
        const foreground = getComputedStyle(element).color;
        const backgroundColor = getComputedStyle(background).backgroundColor;
        const values = [luminance(foreground), luminance(backgroundColor)].sort((a, b) => b - a);
        contrast.push({selector: `.${element.className}`, foreground, background: backgroundColor, ratio: (values[0] + 0.05) / (values[1] + 0.05), required_ratio: 4.5});
      }
      return {contrast, regions: [...document.querySelectorAll('.code-block pre')].map(element => ({role: element.getAttribute('role'), label: element.getAttribute('aria-label'), tabindex: element.tabIndex})), first_scroll_needed: document.querySelector('.code-block pre').scrollWidth > document.querySelector('.code-block pre').clientWidth};
    });
    const code = page.locator('.code-block pre').first();
    await code.focus();
    const beforeScroll = await code.evaluate(element => element.scrollLeft);
    for (let press = 0; press < 10; press++) await page.keyboard.press('ArrowRight');
    await page.waitForTimeout(200);
    const afterScroll = await code.evaluate(element => element.scrollLeft);
    (record.code_support ||= []).push({width, ...codeSupport, keyboard_scroll_before: beforeScroll, keyboard_scroll_after: afterScroll});
    check('code-computed-contrast', codeSupport.contrast.every(item => item.ratio >= item.required_ratio), {width});
    check('code-named-regions', codeSupport.regions.every(item => item.role === 'region' && item.label && item.tabindex === 0), {width});
    check('code-keyboard-scroll', !codeSupport.first_scroll_needed || afterScroll > beforeScroll, {width});
    console.log(JSON.stringify({phase: 'matrix-and-keyboard', engine: record.engine, width, axe_cases: record.accessibility.length}));
  }
  const typographyRoutes = [
    ['central', '/'], ['firing-detail', '/incidents/1?status=firing'],
    ['recovered-detail', '/incidents/2?status=resolved'],
    ['runbook-context', '/runbooks/erp?incident_id=1&status=firing'],
    ['long', '/__review/long'], ['volume', '/__review/volume'], ['read-failure', '/__review/error'],
  ];
  record.typography_scope = 'CSS text sizes doubled individually and WCAG text-spacing values via self-hosted fixture stylesheets. Not native browser zoom or a screen-reader test.';
  for (const width of widths) {
    await page.setViewportSize({width, height: 1000});
    for (const [name, route] of typographyRoutes) {
      for (const kind of ['text-spacing', 'text-enlarge']) {
        await page.goto(new URL(route, origin).href);
        const sizes = await page.evaluate(kind => {
          document.documentElement.classList.add(`review-${kind}`);
          const sizes = new Set();
          for (const element of document.querySelectorAll('body *')) {
            if (![...element.childNodes].some(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim())) continue;
            const size = Number(parseFloat(getComputedStyle(element).fontSize).toFixed(3));
            element.setAttribute('data-review-font-size', String(size));
            sizes.add(size);
          }
          return [...sizes].sort((a, b) => a - b);
        }, kind);
        const sheetURL = new URL(`/__review/assets/${kind}.css`, origin);
        if (kind === 'text-enlarge') sheetURL.searchParams.set('sizes', sizes.join(','));
        const sheetResponse = page.waitForResponse(response => response.url() === sheetURL.href);
        await page.evaluate(url => new Promise((resolve, reject) => {
          const link = document.createElement('link');
          link.rel = 'stylesheet'; link.href = url;
          link.onload = resolve; link.onerror = reject;
          document.head.append(link);
        }), sheetURL.href);
        const stylesheet = await sheetResponse;
        const geometry = await page.evaluate(() => ({
          viewport: innerWidth, content_width: document.documentElement.scrollWidth,
          text_nodes: [...document.querySelectorAll('[data-review-font-size]')].filter(element => element.getClientRects().length).map(element => ({before: Number(element.dataset.reviewFontSize), after: parseFloat(getComputedStyle(element).fontSize)})),
          primary_targets: [...document.querySelectorAll('a.button, button, input, nav.filters a')].filter(element => element.getClientRects().length).map(element => ({tag: element.tagName, width: element.getBoundingClientRect().width, height: element.getBoundingClientRect().height})),
        }));
        (record.typography_cases ||= []).push({name, route, width, kind, stylesheet_self: sheetURL.origin === origin.origin, stylesheet_status: stylesheet.status(), ...geometry});
        check('css-typography-reflow', stylesheet.ok() && geometry.content_width <= width, {name, route, width, kind, content_width: geometry.content_width});
        check('primary-target-minimum-24px', geometry.primary_targets.every(item => item.width >= 24 && item.height >= 24), {name, route, width, kind});
        if (kind === 'text-enlarge') check('css-text-is-200-percent', geometry.text_nodes.every(item => Math.abs(item.after / item.before - 2) < 0.01), {name, route, width});
      }
    }
    console.log(JSON.stringify({phase: 'css-text-and-spacing', engine: record.engine, width}));
  }
  await page.goto(origin.href);
  await page.keyboard.press('Tab');
  await expect(page.getByRole('link', {name: 'Pular para o conteúdo'})).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('#conteudo')).toBeFocused();
  check('skip-link-keyboard', true);
  await page.goto(new URL('/incidents/3', origin).href);
  check('manual-reconciliation-distinct', (await page.locator('body').innerText()).includes('Não foi recebida uma entrega de recuperação'));
  await page.goto(new URL('/incidents/2', origin).href);
  const recoveredText = await page.locator('body').innerText();
  check('recovered-and-late-firing-distinct', recoveredText.includes('Recuperação confirmada') && recoveredText.includes('Firing atrasado ignorado'));
  await page.goto(new URL('/__review/volume', origin).href);
  check('maximum-100-rows', await page.locator('.incident-row').count() === 100);
  await page.goto(new URL('/__review/no-sli', origin).href);
  check('missing-sli-not-claimed-healthy', (await page.locator('body').innerText()).includes('Probe desativado'));
  await page.goto(new URL('/__review/expired-trace', origin).href);
  await page.getByRole('link', {name: 'Voltar à central', exact: true}).click();
  check('expired-trace-fixture-return', new URL(page.url()).pathname === '/');

  async function clockScenario(name, callback, offset = 0) {
    const isolated = await browser.newContext({viewport: {width: 390, height: 1000}, locale: 'pt-BR', timezoneId: 'America/Sao_Paulo', reducedMotion: 'reduce'});
    const timed = await isolated.newPage();
    timed.on('pageerror', error => record.page_errors.push(error.name));
    const start = Date.now();
    const simulation = {name, fixture_time: info.fixture_time, wall_offset_ms: offset, clock: 'Date-only initScript epoch offset; native elapsed time/timers/performance/Navigation Timing; no fastForward'};
    try {
      // Playwright 1.63 Clock APIs replace performance.getEntriesByType with an
      // empty list. This receiver deliberately fails closed without Navigation
      // Timing, so keep all deadline/timer/navigation APIs native. Only shift
      // Date's epoch; the offset stays identical across Back and new documents.
      await isolated.addInitScript(({wallAtStart, nativeAtStart}) => {
        const NativeDate = Date;
        const nativeNow = NativeDate.now.bind(NativeDate);
        const epochOffset = wallAtStart - nativeAtStart;
        function FixtureDate(...values) {
          if (new.target) return Reflect.construct(NativeDate, values.length ? values : [nativeNow() + epochOffset], new.target);
          return new NativeDate(nativeNow() + epochOffset).toString();
        }
        Object.setPrototypeOf(FixtureDate, NativeDate);
        FixtureDate.prototype = NativeDate.prototype;
        FixtureDate.now = () => nativeNow() + epochOffset;
        globalThis.Date = FixtureDate;
      }, {wallAtStart: Date.parse(info.fixture_time) + offset, nativeAtStart: Date.now()});
      await callback(timed, simulation);
    } catch (error) {
      check(name, false, {error_type: error.name});
    } finally {
      simulation.real_elapsed_ms = Date.now() - start;
      (record.clock_scenarios ||= []).push(simulation);
      await isolated.close();
    }
  }
  await clockScenario('observation-expiry-and-back', async (timed, simulation) => {
    await timed.goto(new URL('/__review/fresh', origin).href);
    simulation.initial_title = await timed.locator('[data-observation-title]').textContent();
    simulation.navigation_entries = await timed.evaluate(() => performance.getEntriesByType('navigation').length);
    check('native-navigation-timing-preserved', simulation.navigation_entries === 1);
    await expect(timed.locator('[data-observation-title]')).toHaveText('Consulta de referência validada');
    await timed.waitForFunction(() => document.querySelector('[data-observation-title]')?.textContent === 'Resultado desatualizado', undefined, {timeout: 19000});
    check('elapsed-observation-deadline', true);
    await timed.goto(origin.href);
    await timed.goBack();
    await timed.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const retained = await timed.locator('[data-observation-title]').textContent();
    simulation.title_after_back = retained;
    simulation.return_navigation_type = await timed.evaluate(() => performance.getEntriesByType('navigation')[0]?.type || 'unavailable');
    check('expired-observation-not-renewed-on-back', retained === 'Resultado desatualizado');
  });
  await clockScenario('deferred-script-expiry', async (timed, simulation) => {
    await timed.route('**/snapshot.js', async route => {
      await new Promise(resolve => setTimeout(resolve, 16000));
      await route.continue();
    }, {times: 1});
    await timed.goto(new URL('/__review/fresh', origin).href, {timeout: 25000});
    simulation.real_script_delay_ms = 16000;
    simulation.title_after_script = await timed.locator('[data-observation-title]').textContent();
    check('deferred-script-does-not-renew-expired-observation', simulation.title_after_script === 'Resultado desatualizado');
  });
  await clockScenario('forward-wall-drift', async (timed, simulation) => {
    await timed.goto(new URL('/__review/fresh', origin).href);
    simulation.title_with_wall_drift = await timed.locator('[data-observation-title]').textContent();
    check('forward-wall-clock-past-expiry-is-stale', simulation.title_with_wall_drift === 'Resultado desatualizado');
  }, 30000);
  await page.goto(new URL('/?status=resolved', origin).href);
  const update = page.getByRole('link', {name: 'Atualizar leitura', exact: true});
  await expect(update).toHaveAttribute('href', '/?status=resolved');
  await page.route('**/?status=resolved', async route => {
    const failure = await route.fetch({url: new URL('/__review/update-failure', origin).href});
    await route.fulfill({response: failure});
  }, {times: 1});
  await update.click();
  await expect(page.getByRole('heading', {name: 'Histórico indisponível', exact: true})).toBeVisible();
  await page.getByRole('link', {name: 'Voltar à central', exact: true}).click();
  await expect(page.locator('h1')).toHaveText('Incidentes');
  check('manual-update-503-and-return', true);
  check('all-keyboard-journeys', record.journeys.every(journey => journey.passed));
}

(async () => {
  let browser;
  try {
    browser = await playwright[record.engine].launch({headless: true, executablePath: args['--browser-executable'] || undefined});
    record.browser_version = browser.version();
    const context = await browser.newContext({viewport: {width: 1440, height: 1000}, locale: 'pt-BR', timezoneId: 'America/Sao_Paulo', reducedMotion: 'reduce'});
    const page = await context.newPage();
    page.on('pageerror', error => record.page_errors.push(error.name));
    page.setDefaultTimeout(10000);
    const routes = [
      ['central', '/', 200], ['firing-detail', '/incidents/1?status=firing', 200],
      ['recovered-detail', '/incidents/2?status=resolved', 200],
      ['runbook-context', '/runbooks/erp?incident_id=1&status=firing', 200],
      ['read-failure', '/__review/error', 503],
    ];
    for (const width of [1440, 1024, 768, 390, 320]) {
      await page.setViewportSize({width, height: 1000});
      for (const [name, route, status] of routes) {
        const response = await page.goto(new URL(route, origin).href);
        assert(response?.status() === status, 'Capture route must respond with its declared fixture status');
        assert(response.headers()['content-security-policy']?.includes("default-src 'none'"), 'Production CSP must remain enabled');
        await page.evaluate(() => document.fonts.ready);
        assert.equal(await page.locator('.review-note').count(), 1, 'Every page must identify its synthetic fixture');
        const state = await page.evaluate(() => ({width: innerWidth, content_width: document.documentElement.scrollWidth, fonts_loaded: [...document.fonts].every(font => font.status === 'loaded'), headings: document.querySelectorAll('h1').length}));
        assert(state.fonts_loaded && state.headings === 1, 'Capture needs loaded fonts and one page heading');
        record.views.push({name, route, ...state, horizontal_overflow: state.content_width > width});
        const filename = `${name}-${width}.png`;
        await page.screenshot({path: path.join(output, filename), fullPage: true, animations: 'disabled'});
        const pixels = fs.readFileSync(path.join(output, filename));
        record.images.push({file: filename, width, route, viewport: {width, height: 1000}, dimensions: {width: pixels.readUInt32BE(16), height: pixels.readUInt32BE(20)}, sha256: sha(pixels)});
      }
    }
    assert.deepEqual(record.page_errors, [], 'No uncaught page errors are allowed');
    if (record.mode === 'audit') await auditUI(page, context, browser);
    check('no-uncaught-page-errors', record.page_errors.length === 0);
    record.status = record.mode === 'capture' ? 'captured' : (record.checks.every(item => item.passed) ? 'passed' : 'failed');
    await context.close();
  } catch (error) {
    record.status = 'failed';
    record.failure_type = error.name;
    throw error;
  } finally {
    record.source_files_sha256_after = fingerprint();
    record.source_unchanged = sorted(before) === sorted(record.source_files_sha256_after);
    record.context_fixture_sha256_after = sha(fs.readFileSync(fixturePath));
    record.context_fixture_unchanged = fixtureBefore === record.context_fixture_sha256_after;
    record.server_helper_unchanged = serverHelperBefore === sha(fs.readFileSync(serverHelperPath));
    if (!record.source_unchanged || !record.context_fixture_unchanged || !record.server_helper_unchanged) record.status = 'failed';
    record.finished_at = new Date().toISOString();
    fs.writeFileSync(path.join(output, 'capture.json'), JSON.stringify(record, null, 2) + '\n');
    await browser?.close();
    assert(record.source_unchanged, 'Fixture source changed during captures');
    assert(record.context_fixture_unchanged && record.server_helper_unchanged, 'Fixture or helper changed during captures');
  }
  console.log(JSON.stringify({status: record.status, source_commit: record.source_commit, engine: record.engine, images: record.images.length, source_unchanged: record.source_unchanged, checks: record.checks.length, failed_checks: record.checks.filter(item => !item.passed).length, keyboard_journeys: record.journeys.length}));
  if (record.status === 'failed') process.exitCode = 1;
})().catch(error => {console.error(JSON.stringify({status: 'failed', error_type: error.name})); process.exitCode = 1;});
