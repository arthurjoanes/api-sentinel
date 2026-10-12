const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const assert=require('node:assert/strict');
const playwright=require(process.env.PLAYWRIGHT_MODULE || path.resolve('tools/ui-review/node_modules/@playwright/test'));
const output=path.resolve('.runtime/ui-ux-20261012/pairs-viewport-01');
assert(!fs.existsSync(output)); fs.mkdirSync(output);
const hash=value=>crypto.createHash('sha256').update(value).digest('hex');
const fingerprint=info=>Object.fromEntries(Object.keys(info.source_files_sha256_before).sort().map(name=>[name,hash(fs.readFileSync(path.join(info.source,name)))]));
const entries=[['baseline','baseline-server-03'],['final02','candidate-server-02']].map(([name,folder])=>{
  const info=JSON.parse(fs.readFileSync(`.runtime/ui-ux-20261012/${folder}/server.json`,'utf8'));
  const before=fingerprint(info); assert.deepEqual(before,info.source_files_sha256_before);
  const db=path.resolve(`.runtime/ui-ux-20261012/${folder}/private/alerts.sqlite3`);
  return {name,info,before,db,dbBefore:hash(fs.readFileSync(db))};
});
const record={scope:'Viewport-only central pairs for synthetic isolated receiver; probe disabled; no stack health claim',fullPage:false,engine:'chromium',node:process.version,playwright_version:'1.63.0',locale:'pt-BR',timezone:'America/Sao_Paulo',browser_clock:'Native Date and performance; no simulation or clock override for these screenshots',tool_sha256:hash(fs.readFileSync(__filename)),frames:[],page_errors:[],sources:[]};
fs.copyFileSync(__filename,path.join(output,'capture-pairs.cjs'));
(async()=>{
  const browser=await playwright.chromium.launch({headless:true,executablePath:(process.env.CHROMIUM_EXECUTABLE || undefined)});
  record.browser_version=browser.version();
  try{
    for(const width of [1440,390]){
      const context=await browser.newContext({viewport:{width,height:1000},locale:'pt-BR',timezoneId:'America/Sao_Paulo',reducedMotion:'reduce'});
      const page=await context.newPage(); page.on('pageerror',e=>record.page_errors.push(e.name));
      for(const entry of entries){
        const response=await page.goto(entry.info.url+'/');
        assert.equal(response.status(),200);
        assert(response.headers()['content-security-policy'].includes("default-src 'none'"));
        await page.evaluate(()=>document.fonts.ready);
        assert.equal(await page.locator('.review-note').count(),1);
        const file=`${entry.name}-central-${width}.png`;
        await page.screenshot({path:path.join(output,file),fullPage:false,animations:'disabled'});
        const bytes=fs.readFileSync(path.join(output,file));
        const dimensions={width:bytes.readUInt32BE(16),height:bytes.readUInt32BE(20)};
        assert.deepEqual(dimensions,{width,height:1000});
        record.frames.push({file,source:entry.name,source_commit:entry.info.source_commit,fixture_time:entry.info.fixture_time,route:'/',viewport:{width,height:1000},dimensions,fullPage:false,sha256:hash(bytes),state:await page.evaluate(()=>({viewport:innerWidth,content_width:document.documentElement.scrollWidth,fonts_loaded:[...document.fonts].every(f=>f.status==='loaded'),wall_epoch_ms:Date.now()}))});
      }
      await context.close();
    }
  }finally{
    for(const entry of entries){
      const after=fingerprint(entry.info);
      const dbAfter=hash(fs.readFileSync(entry.db));
      record.sources.push({name:entry.name,source_commit:entry.info.source_commit,fixture_time:entry.info.fixture_time,source_files_sha256_before:entry.before,source_files_sha256_after:after,source_unchanged:JSON.stringify(entry.before)===JSON.stringify(after),context_fixture_sha256_before:entry.dbBefore,context_fixture_sha256_after:dbAfter,context_fixture_unchanged:entry.dbBefore===dbAfter});
    }
    record.status=record.frames.length===4&&record.page_errors.length===0&&record.sources.every(s=>s.source_unchanged&&s.context_fixture_unchanged)?'captured':'failed';
    fs.writeFileSync(path.join(output,'pairs.json'),JSON.stringify(record,null,2)+'\n');
    await browser.close();
  }
  assert.equal(record.status,'captured');
  console.log(JSON.stringify({status:record.status,images:record.frames.length,fullPage:false,dimensions:record.frames.map(f=>({file:f.file,...f.dimensions})),source_unchanged:record.sources.every(s=>s.source_unchanged)}));
})();
