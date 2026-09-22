const fs=require('node:fs');
const {chromium,expect}=require(process.env.PLAYWRIGHT_MODULE || '@playwright/test');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const base='http://127.0.0.1:9818', results={checkedAt:new Date().toISOString(),data:[],performance:[],controls:[]};
 try {
  for(const status of ['all','firing','resolved']){
   const snapshots=[];
   for(const route of [`/__baseline?status=${status}`,`/?status=${status}`]){
    await page.goto(base+route);
    const values=await page.locator('.incident-row').evaluateAll(rows=>rows.map(row=>({id:row.id,title:row.querySelector('h3').textContent,impact:row.querySelector('.row-description > p').textContent,state:row.querySelector('.badge').textContent,observed:row.querySelector('time').textContent,facts:[...row.querySelectorAll('.row-facts dd')].map(e=>e.textContent.trim())})));
    snapshots.push(values);
   }
   expect(snapshots[0]).toEqual(snapshots[1]);
   results.data.push({status,equivalent:true,rows:snapshots[1]});
  }
  for(const width of [1440,390]){
   await page.setViewportSize({width,height:1000});
   for(const [name,route] of [['baseline','/__volume?baseline_view=true'],['candidate','/__volume']]){
    const samples=[];let final;
    for(let i=0;i<6;i++){
     const response=await page.goto(base+route);
     await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
     final=await page.evaluate(()=>{const n=performance.getEntriesByType('navigation')[0]; return {domReadyMs:n.domContentLoadedEventEnd-n.startTime,domNodes:document.querySelectorAll('*').length,rows:document.querySelectorAll('.incident-row').length,overflow:document.documentElement.scrollWidth>innerWidth,scriptCount:document.scripts.length,externalResources:performance.getEntriesByType('resource').map(r=>r.name).filter(url=>new URL(url).origin!==location.origin)};});
     samples.push(final.domReadyMs);final.htmlBytes=(await response.body()).length;
    }
    expect(final.rows).toBe(100);expect(final.overflow).toBe(false);expect(final.externalResources).toEqual([]);
    const sorted=[...samples.slice(1)].sort((a,b)=>a-b);
    results.performance.push({name,width,...final,domReadyMsSamples:samples,warmMedianMs:sorted[2],scope:'One warmup + five local loads; no CPU/network throttling; synthetic 100-row maximum; not a production SLA or INP measurement'});
   }
  }
  await page.setViewportSize({width:390,height:1000});
  for(const route of ['/','/incidents/2','/runbooks','/runbooks/erp','/__review/empty','/tools/grafana/']){
   await page.goto(base+route);
   const small=await page.locator('a,summary').evaluateAll(els=>els.filter(e=>e.checkVisibility({checkVisibilityCSS:true})).map(e=>({text:e.textContent.trim(),width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height})).filter(e=>e.width<24||e.height<24));
   results.controls.push({route,smallTargets:small});
   expect(small).toEqual([]);
  }
  await page.goto(base+'/incidents/2?status=resolved');
  await expect(page.locator('.decision-actions .button')).toHaveText('Conferir observação atual');
  await page.getByRole('link',{name:'Conferir observação atual'}).focus();await page.keyboard.press('Enter');
  await expect(page.locator('#observacao summary')).toBeFocused();
  await expect(page.locator('.filters [aria-current=page]')).toHaveAttribute('href','/?status=resolved');
  await page.goto(base+'/incidents/1?status=firing');
  await expect(page.locator('.decision-actions .button')).toHaveText('Abrir runbook');
  await page.goto(base+'/runbooks/erp');
  await page.setViewportSize({width:320,height:1000});
  const code=page.locator('pre').first();await code.focus();await page.keyboard.press('End');
  await expect(code).toBeFocused();
  results.keyboard={recoveredObservationReturnsFilterAndFocus:true,activeRunbookPrimary:true,codeFocusable:true};
  await page.goto(base+'/');
  await page.route('**/?status=firing', async route=>{await new Promise(resolve=>setTimeout(resolve,250));await route.continue().catch(()=>{});},{times:1});
  const first=page.goto(base+'/?status=firing').catch(e=>e.message);
  await new Promise(resolve=>setTimeout(resolve,40));
  await page.goto(base+'/?status=resolved');await first;
  await expect(page.locator('.filters [aria-current=page]')).toHaveAttribute('href','/?status=resolved');
  await expect(page.locator('.incident-row')).toHaveCount(2);
  results.fastNavigation={delayedFiringRequestMs:250,latestResolvedRemains:true,mechanism:'Native document navigation; no shared client response cache'};
  fs.writeFileSync('.runtime/art-review/extended-review.json',JSON.stringify(results,null,2));
  console.log(JSON.stringify(results,null,2));
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
