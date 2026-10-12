const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const {chromium,expect}=require(process.env.PLAYWRIGHT_MODULE || path.resolve('tools/ui-review/node_modules/@playwright/test'));
const info=JSON.parse(fs.readFileSync('.runtime/ui-ux-20261012/candidate-server-02/server.json','utf8'));
const output='.runtime/ui-ux-20261012/candidate-supplement-02';
if(fs.existsSync(output)) throw Error('Use a new evidence directory'); fs.mkdirSync(output);
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const fingerprint=()=>Object.fromEntries(Object.keys(info.source_files_sha256_before).sort().map(n=>[n,hash(fs.readFileSync(path.join(info.source,n)))]));
const before=fingerprint();
const db='.runtime/ui-ux-20261012/candidate-server-02/private/alerts.sqlite3';
const dbBefore=hash(fs.readFileSync(db));
const record={scope:'Supplement: native Tab+Enter activation of complete routes; CSS sizing of input values/placeholders and visible clipping/interactive overlaps only. No screen-reader/native zoom claim.',source_commit:info.source_commit,fixture_time:info.fixture_time,engine:'chromium',playwright_version:'1.63.0',node:process.version,browser_clock:'Native Date/performance; default receiver probe disabled',tool_sha256:hash(fs.readFileSync(__filename)),journeys:[],typography:[],errors:[]};
fs.copyFileSync(__filename,path.join(output,'supplement.cjs'));
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:(process.env.CHROMIUM_EXECUTABLE || undefined)});
 record.browser_version=browser.version();
 try{
  const page=await browser.newPage({locale:'pt-BR',timezoneId:'America/Sao_Paulo',reducedMotion:'reduce'});
  page.on('pageerror',e=>record.errors.push(e.name));
  for(const width of [320,390,768,1024,1440]){
   await page.setViewportSize({width,height:1000});
   async function activate(locator,destination){
    await expect(locator).toBeVisible();
    let tabs=0;
    while(!await locator.evaluate(n=>n===document.activeElement)){
     if(tabs++>=100) throw Error('Keyboard target unreachable');
     await page.keyboard.press('Tab');
    }
    await Promise.all([page.waitForURL(new URL(destination,info.url).href),page.keyboard.press('Enter')]);
    await page.waitForLoadState('domcontentloaded');
    return tabs;
   }
   for(const status of ['all','firing','resolved']){
    const item={width,status,activation:'Tab+Enter only; no focus() or mouse click',tab_steps:[]};
    try{
     await page.goto(info.url+'/');
     item.tab_steps.push(await activate(page.locator(`nav[aria-label="Filtrar incidentes"] a[href="/?status=${status}"]`),`/?status=${status}`));
     const incident=page.locator('a[href^="/incidents/"]').first();
     const destination=await incident.getAttribute('href'); const id=destination.match(/incidents\/(\d+)/)[1];
     item.tab_steps.push(await activate(incident,destination));
     const runbook=page.locator('main a[href^="/runbooks/"]').first();
     item.tab_steps.push(await activate(runbook,await runbook.getAttribute('href')));
     const section=page.locator('main a[href^="#"]').first(); const sectionId=(await section.getAttribute('href')).slice(1);
     item.tab_steps.push(await activate(section,new URL(page.url()).pathname+new URL(page.url()).search+'#'+sectionId));
     await expect(page.locator('#'+sectionId)).toBeFocused();
     item.tab_steps.push(await activate(page.locator(`a[href="${destination}"]`).first(),destination));
     const back=`/?status=${status}#incidente-${id}`;
     item.tab_steps.push(await activate(page.locator(`a[href="${back}"]`),back));
     await expect(page.locator('#incidente-'+id)).toBeFocused();
     await expect(page.locator('nav[aria-label="Filtrar incidentes"] [aria-current]')).toHaveAttribute('href',`/?status=${status}`);
     await page.goBack(); await expect(page).toHaveURL(new URL(destination,info.url).href);
     item.passed=true;
    }catch(e){item.passed=false;item.error_type=e.name;}
    record.journeys.push(item);
   }
   for(const route of ['/','/incidents/1?status=firing','/incidents/2?status=resolved']){
    for(const kind of ['text-spacing','text-enlarge']){
     await page.goto(info.url+route); await page.evaluate(()=>document.fonts.ready);
     if(await page.locator('input').count()) await page.locator('input').first().pressSequentially('123');
     const sizes=await page.evaluate(kind=>{
      document.documentElement.classList.add('review-'+kind); const sizes=new Set();
      for(const e of document.querySelectorAll('body *')){
       if(!e.matches('input,textarea,select')&&![...e.childNodes].some(n=>n.nodeType===Node.TEXT_NODE&&n.textContent.trim())) continue;
       const s=Number(parseFloat(getComputedStyle(e).fontSize).toFixed(3));e.dataset.reviewFontSize=String(s);sizes.add(s);
      }
      return [...sizes].sort((a,b)=>a-b);
     },kind);
     const url=new URL('/__review/assets/'+kind+'.css',info.url);if(kind==='text-enlarge')url.searchParams.set('sizes',sizes.join(','));
     await page.evaluate(url=>new Promise((resolve,reject)=>{const e=document.createElement('link');e.rel='stylesheet';e.href=url;e.onload=resolve;e.onerror=reject;document.head.append(e);}),url.href);
     const facts=await page.evaluate(()=>{
      const visible=e=>{
       if(!e.getClientRects().length||e.closest('.visually-hidden'))return false;
       for(let p=e.parentElement;p;p=p.parentElement){
        const s=getComputedStyle(p);
        if(s.display==='none'||s.visibility==='hidden'||s.visibility==='collapse')return false;
        if(p.tagName==='DETAILS'&&!p.open&&!p.querySelector(':scope > summary')?.contains(e))return false;
       }
       return true;
      };
      const inputs=[...document.querySelectorAll('input,textarea,select')].filter(visible).map(e=>{const s=getComputedStyle(e);return {before:Number(e.dataset.reviewFontSize),after:parseFloat(s.fontSize),line_height:parseFloat(s.lineHeight),inner_height:e.clientHeight-parseFloat(s.paddingTop)-parseFloat(s.paddingBottom),value_or_placeholder_present:Boolean(e.value||e.getAttribute('placeholder'))};});
      const clipped=[...document.querySelectorAll('[data-review-font-size]')].filter(visible).filter(e=>{const s=getComputedStyle(e);return (['hidden','clip'].includes(s.overflowY)&&e.scrollHeight>e.clientHeight+1)||(['hidden','clip'].includes(s.overflowX)&&e.scrollWidth>e.clientWidth+1);}).map(e=>({tag:e.tagName,class:e.className,scroll_width:e.scrollWidth,client_width:e.clientWidth,scroll_height:e.scrollHeight,client_height:e.clientHeight}));
      const controls=[...document.querySelectorAll('a,button,input,summary')].filter(visible).map(e=>({e,r:e.getBoundingClientRect()})).filter(o=>o.r.bottom>0&&o.r.width&&o.r.height);
      const overlaps=[];
      for(let i=0;i<controls.length;i++)for(let j=i+1;j<controls.length;j++){
       const a=controls[i],b=controls[j];if(a.e.contains(b.e)||b.e.contains(a.e))continue;
       const x=Math.min(a.r.right,b.r.right)-Math.max(a.r.left,b.r.left),y=Math.min(a.r.bottom,b.r.bottom)-Math.max(a.r.top,b.r.top);
       if(x>1&&y>1)overlaps.push({a:a.e.tagName+'.'+a.e.className,b:b.e.tagName+'.'+b.e.className,width:x,height:y});
      }
      return {content_width:document.documentElement.scrollWidth,viewport:innerWidth,inputs,clipped,interactive_overlaps:overlaps};
     });
     record.typography.push({width,route,kind,...facts,passed:facts.content_width<=width&&!facts.clipped.length&&!facts.interactive_overlaps.length&&facts.inputs.every(i=>i.line_height<=i.inner_height+1&&(kind!=='text-enlarge'||Math.abs(i.after/i.before-2)<.01))});
    }
   }
   console.log(JSON.stringify({phase:'supplement',width}));
  }
 }finally{
  record.source_files_sha256_before=before;record.source_files_sha256_after=fingerprint();record.source_unchanged=JSON.stringify(before)===JSON.stringify(record.source_files_sha256_after);
  record.context_fixture_sha256_before=dbBefore;record.context_fixture_sha256_after=hash(fs.readFileSync(db));record.context_fixture_unchanged=dbBefore===record.context_fixture_sha256_after;
  record.status=record.journeys.length===15&&record.journeys.every(j=>j.passed)&&record.typography.length===30&&record.typography.every(c=>c.passed)&&!record.errors.length&&record.source_unchanged&&record.context_fixture_unchanged?'passed':'failed';
  fs.writeFileSync(path.join(output,'supplement.json'),JSON.stringify(record,null,2)+'\n');await browser.close();
 }
 console.log(JSON.stringify({status:record.status,journeys:record.journeys.length,failed_journeys:record.journeys.filter(j=>!j.passed).length,typography:record.typography.length,failed_typography:record.typography.filter(c=>!c.passed).length}));
 if(record.status!=='passed')process.exitCode=1;
})();
