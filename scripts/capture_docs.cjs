// Capture current rendered pages without changing application data.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {pathToFileURL,fileURLToPath} = require('node:url');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const source = process.argv[2];
const reference = value => {
  if (value.startsWith('file:')) {
    const url = new URL(value); const fragment = url.hash; url.hash='';
    return path.relative(root,fileURLToPath(url)).split(path.sep).join('/')+fragment;
  }
  return path.isAbsolute(value) ? path.relative(root,value).split(path.sep).join('/') : value;
};
const output = process.argv[3] && path.resolve(process.argv[3]);
if (!source || !output) throw new Error('Usage: node scripts/capture_docs.cjs <source> <new-output-directory>');
if (fs.existsSync(output)) throw new Error('Output already exists; use a new directory to preserve previous captures.');
fs.mkdirSync(output, {recursive:true});
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
(async () => {
  const browser = await chromium.launch({headless:true, channel:process.env.PLAYWRIGHT_CHANNEL || undefined,
    executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH || undefined});
  const record = {capturedAt:new Date().toISOString(), browser:browser.version(),
    scope:'Current live receiver, GET navigation only; retained incident records are not a new failure/recovery experiment', source:reference(source), views:[], images:[], pageErrors:[], sourceFiles:{}};
  try {
    for (const file of ['alert_receiver/ui.py','alert_receiver/styles.css','alert_receiver/snapshot.js']) record.sourceFiles[file] = sha(fs.readFileSync(path.join(root,file)));
    const page = await browser.newPage({viewport:{width:1440,height:1000}, reducedMotion:'reduce', locale:'pt-BR'});
    page.on('pageerror', error => record.pageErrors.push(error.message));
    page.setDefaultTimeout(15000);

    const base = new URL(source);
    assert.ok(['127.0.0.1','localhost'].includes(base.hostname),'Use a local receiver');
    await page.goto(base.href);
    const detail = await page.locator('a[href^="/incidents/"]').first().getAttribute('href');
    const routes = [['central',base.href],['finalizados',new URL('/?status=resolved',base).href],
      ['runbooks',new URL('/runbooks',base).href],['runbook-erp',new URL('/runbooks/erp',base).href]];
    if(detail) routes.push(['incidente',new URL(detail,base).href]);

    for (const width of [1120,390,320]) {
      await page.setViewportSize({width,height:1000});
      for (const [name,url] of routes) {
        const response = await page.goto(url);
        if (response) assert.ok(response.ok(), `${url}: ${response.status()}`);
        await page.evaluate(() => document.fonts.ready);

        const state = await page.evaluate(() => ({title:document.title,
          width:innerWidth, scrollWidth:document.documentElement.scrollWidth,
          fonts:[...document.fonts].map(f=>({family:f.family,status:f.status})),
          h1:document.querySelector('h1')?.textContent?.trim()}));
        assert.ok(state.scrollWidth <= width, `${name} horizontal overflow at ${width}`);
        assert.ok(state.fonts.every(font=>font.status==='loaded'), `${name} fonts not loaded`);
        const view = {name,width,url:reference(url),...state};
        record.views.push(view);
      }
    }

    async function crop(name, routeName, width, startSelector, endSelector) {
      await page.setViewportSize({width,height:1000});
      const url = routes.find(([key])=>key===routeName)[1];
      await page.goto(url); await page.evaluate(()=>document.fonts.ready);
      if(routeName==='recovery') await page.locator('.recovery-job').evaluate(el=>el.open=true);
      await page.evaluate(()=>scrollTo(0,0));
      const first=await page.locator(startSelector).boundingBox();
      const last=await page.locator(endSelector || startSelector).boundingBox();
      assert.ok(first && last, name+' focus not found');
      const clip={x:Math.max(0,Math.floor(first.x)-8),y:Math.max(0,Math.floor(first.y)-8),
        width:Math.min(width-Math.max(0,Math.floor(first.x)-8),Math.ceil(first.width)+16),
        height:Math.ceil(last.y+last.height-first.y)+16};
      assert.ok(width<600 ? clip.height<=650 : clip.height/clip.width<=1.1,name+' capture is too long');
      await page.mouse.move(0,0); await page.evaluate(()=>document.activeElement?.blur());
      const image=name+'.png';
      await page.screenshot({path:path.join(output,image),clip});
      const imageBytes=fs.readFileSync(path.join(output,image));
      assert.equal(imageBytes.subarray(0,8).toString('hex'),'89504e470d0a1a0a');
      assert.equal(imageBytes.subarray(12,16).toString(),'IHDR');
      const imageDimensions={width:imageBytes.readUInt32BE(16),height:imageBytes.readUInt32BE(20)};
      record.images.push({image,imageDimensions,url:reference(url),viewport:{width,height:1000},clip,
        focus:{startSelector,endSelector:endSelector || startSelector},sha256:sha(imageBytes)});
    }

    await crop('fila-foco','central',1120,'.inbox','.incident-row:nth-child(2)');
    await crop('fila-movel-foco','central',390,'.inbox','.incident-row:first-child');
    if(routes.some(([key])=>key==='incidente')) await crop('historico-foco','incidente',1120,'.history','.timeline-event:last-child');
    assert.deepEqual(record.pageErrors,[]);
    record.status='passed';
  } catch(error) {record.status='failed';record.error=error.message;throw error;}
  finally {fs.writeFileSync(path.join(output,'capture.json'),JSON.stringify(record,null,2)+'\n');await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
