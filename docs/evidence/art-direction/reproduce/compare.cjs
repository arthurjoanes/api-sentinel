const fs=require('node:fs');
const {chromium,expect}=require(process.env.PLAYWRIGHT_MODULE || '@playwright/test');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({reducedMotion:'reduce'});
 const checks=[];
 const pairs=[['all','/__baseline?status=all','/?status=all'],['resolved','/__baseline?status=resolved','/?status=resolved'],['recovered','/__baseline/incident/2?status=resolved','/incidents/2?status=resolved']];
 try {
  for(const width of [1920,1440,768,390,320]){
   await page.setViewportSize({width,height:1000});
   for(const [scenario,baseline,candidate] of pairs){
    for(const [name,path] of [['baseline',baseline],['candidate',candidate]]){
     const response=await page.goto('http://127.0.0.1:9818'+path);
     expect(response.status()).toBe(200);
     await page.evaluate(()=>document.fonts.ready);
     const metrics=await page.evaluate(()=>{
      const box=e=>{const r=e.getBoundingClientRect();return {top:r.top,bottom:r.bottom,height:r.height}};
      const rows=[...document.querySelectorAll('.incident-row')].map(box);
      return {viewport:{width:innerWidth,height:innerHeight},documentHeight:document.documentElement.scrollHeight,scrollWidth:document.documentElement.scrollWidth,rows,rowsFullyVisible:rows.filter(r=>r.bottom<=innerHeight).length,detail:document.querySelector('.detail-heading')?box(document.querySelector('.detail-heading')):null};
     });
     const file=`${name}-${scenario}-${width}.png`;
     await page.screenshot({path:'.runtime/art-review/'+file,fullPage:true});
     checks.push({name,scenario,path,width,file,...metrics});
    }
   }
  }
  fs.writeFileSync('.runtime/art-review/comparison.json',JSON.stringify({capturedAt:new Date().toISOString(),baseline:'88dcebdf65399db19563c8bfe1406ab24a110d61',fixture:'same in-process SQLite records, titles and timestamps; disabled probe; all/resolved filters and recovered incident #2',scope:'geometry in CSS pixels; not productivity or user approval',checks},null,2));
  console.log(JSON.stringify(checks.map(c=>({name:c.name,scenario:c.scenario,width:c.width,firstRow:Math.round(c.rows[0]?.top??0),rowHeight:Math.round(c.rows[0]?.height??0),fullyVisible:c.rowsFullyVisible,detailHeight:Math.round(c.detail?.height??0)})),null,2));
 } finally {await browser.close();}
})();
