const { chromium, expect } = require(process.env.PLAYWRIGHT_MODULE || '@playwright/test');
const fs = require('fs');
const base = 'http://127.0.0.1:9816';
(async () => {
  const browser = await chromium.launch({headless:true, channel:'msedge'});
  const page = await browser.newPage({viewport:{width:1440,height:1000}});
  for (let attempt = 0; attempt < 30; attempt++) {
    const ready = await page.request.get(base+'/health/live').catch(()=>null);
    if (ready?.ok()) break;
    if (attempt === 29) throw Error('Preview did not become ready');
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  const errors = [], overflows = [], journeys = [];
  page.on('pageerror', e => errors.push(e.message));
  for (const width of [1440,768,390,320]) {
    await page.setViewportSize({width,height:1000});
    for (const status of ['all','firing','resolved']) {
      await page.goto(`${base}/?status=${status}`);
      await expect(page.locator('.filters [aria-current=page]')).toHaveAttribute('href',`/?status=${status}`);
      const incidentLink = page.locator('.incident-action').first();
      const destination = await incidentLink.getAttribute('href');
      const id = destination.match(/incidents\/(\d+)/)[1];
      await expect(page.locator('.row-metadata[open]')).toHaveCount(0);
      await page.locator('.row-metadata summary').first().click();
      await expect(page.locator('.row-metadata[open]')).toHaveCount(1);
      await page.locator('.row-metadata summary').first().click();
      await incidentLink.focus();
      await page.keyboard.press('Enter');
      await expect(page.locator('a.back')).toHaveAttribute('href',`/?status=${status}#incidente-${id}`);
      await page.getByRole('link',{name:'Abrir runbook',exact:true}).click();
      await expect(page.locator('a.back')).toHaveAttribute('href',destination);
      const section = page.locator('.runbook-outline nav a').first();
      const sectionId = (await section.getAttribute('href')).slice(1);
      await section.focus(); await page.keyboard.press('Enter');
      await expect(page.locator(`#${sectionId}`)).toBeFocused();
      await page.locator('a.back').click();
      await page.locator('a.back').click();
      await expect(page.locator(`#incidente-${id}`)).toBeFocused();
      await expect(page.locator('.filters [aria-current=page]')).toHaveAttribute('href',`/?status=${status}`);
      journeys.push({width,status,detailRunbookReturn:true,keyboardSectionFocus:true,rowFocus:true});
    }
  }
  const routes = ['/', '/?status=firing','/?status=resolved','/incidents/2?status=resolved',
    '/incidents/3?status=resolved','/runbooks','/runbooks/erp?incident_id=1&status=firing',
    '/tools/grafana/','/__review/empty','/__review/no-active','/__review/stale',
    '/__review/disabled','/__review/failure','/__review/error','/__review/long','/__review/index',
    '/incidents/1','/incidents/999','/?status=invalid','/runbooks/unavailable','/runbooks/replica','/runbooks/error-budget','/runbooks/latency','/runbooks/saturation','/runbooks/telemetry','/tools/jaeger/'];
  for (const width of [1440,768,640,390,320]) {
    await page.setViewportSize({width,height:1000});
    for (const route of routes) {
      await page.goto(base+route);
      const size = await page.evaluate(() => ({viewport:document.documentElement.clientWidth,content:document.documentElement.scrollWidth}));
      if (size.content > size.viewport) overflows.push({width,route,...size});
      await expect(page.locator('h1')).toHaveCount(1);
    }
  }
  await page.goto(base+'/?status=firing#incidente-3');
  await expect(page.locator('#conteudo')).toBeFocused();
  await page.goto(base+'/');
  await page.keyboard.press('Tab');
  await expect(page.getByRole('link',{name:'Pular para o conteúdo'})).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('#conteudo')).toBeFocused();
  await page.goto(base+'/incidents/3');
  await expect(page.locator('.reconciliation')).toContainText('Não foi recebida uma entrega de recuperação');
  await expect(page.locator('.detail-labels .badge')).toHaveText('Encerrado pelo operador');
  await expect(page.locator('.history')).not.toContainText('Recuperação confirmada');
  await page.goto(base+'/incidents/2');
  await expect(page.locator('.history')).toContainText('Firing atrasado ignorado');
  await expect(page.locator('.history')).toContainText('Recuperação confirmada');
  await page.goto(base+'/__review/index');
  await page.locator('.observation-time a').click();
  await expect(page.locator('#observacao')).toHaveAttribute('open','');
  await expect(page.locator('#observacao summary')).toBeFocused();
  await page.clock.install();
  await page.goto(base+'/__review/index');
  await expect(page.locator('[data-observation-title]')).toHaveText('Consulta de referência validada');
  await page.clock.fastForward(16000);
  await expect(page.locator('[data-observation-title]')).toHaveText('Resultado desatualizado');
  await page.clock.resume();
  await page.goto(base+'/__review/disabled');
  await expect(page.locator('[data-observation-title]')).toHaveText('Probe desativado');
  await page.goto(base+'/tools/grafana/');
  await expect(page.getByRole('heading',{name:'Investigação indisponível'})).toBeVisible();
  await page.getByRole('link',{name:'Voltar à central',exact:true}).click();
  await expect(page.locator('h1')).toHaveText('Incidentes');
  await page.emulateMedia({reducedMotion:'reduce'});
  if(await page.locator('.button').evaluate(el=>getComputedStyle(el).transitionDuration)!=='0s') throw Error('Reduced motion did not disable transitions');
  await page.emulateMedia({reducedMotion:'no-preference'});
  const captures = [
    ['central-desktop.png','/',1440],
    ['central-mobile.png','/',390],
    ['finalized-desktop.png','/?status=resolved',1440],
    ['recovered-detail.png','/incidents/2?status=resolved',1440],
    ['runbook-catalog.png','/runbooks',1440],
    ['manual-detail.png','/incidents/3?status=resolved',1440],
    ['runbook-context.png','/runbooks/erp?incident_id=1&status=firing',1440],
    ['tool-unavailable.png','/tools/grafana/',390],
    ['reflow-320.png','/runbooks/erp?incident_id=1&status=firing',320],
    ['state-empty.png','/__review/empty',1440],
    ['state-no-active.png','/__review/no-active',390],
    ['state-stale.png','/__review/stale',1440],
    ['state-failure.png','/__review/failure',390],
    ['state-error.png','/__review/error',1440]
  ];
  for(const [file,route,width] of captures){
    await page.setViewportSize({width,height:1000}); await page.goto(base+route);
    await page.screenshot({path:'.runtime/quality/'+file,fullPage:true});
  }
  const result = {checkedAt:new Date().toISOString(),synthetic:true,widths:[1440,768,640,390,320],routes,journeys,
    overflows,errors,skipLink:true,missingRowFocusFallback:true,manualAndRecoveredDistinct:true,
    probeExpires:true,disabledProbeNeutral:true,unconfiguredToolHtmlRecovery:true,
    reducedMotion:true,zoomScope:'640/320 CSS px verify reflow equivalent to 1280 px at 200%/400%; native browser zoom not measured',captures};
  fs.writeFileSync('.runtime/quality/browser-review.json',JSON.stringify(result,null,2));
  console.log(JSON.stringify(result,null,2)); await browser.close();
  if(errors.length || overflows.length) process.exitCode=1;
})().catch(e=>{console.error(e);process.exit(1)});
