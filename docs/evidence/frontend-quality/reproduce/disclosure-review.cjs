const fs=require('node:fs');
const {chromium,expect}=require(process.env.PLAYWRIGHT_MODULE || '@playwright/test');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});try{
 await page.goto('http://127.0.0.1:9816/incidents/2?status=resolved');
 await page.locator('.incident-metadata summary').click();
 await expect(page.locator('.original-action')).toBeVisible();
 await expect(page.locator('.original-action')).toContainText('Compare espera no pool');
 await page.screenshot({path:'.runtime/quality/recovered-record.png',fullPage:true});
 await page.goto('http://127.0.0.1:9816/__review/index#observacao');
 await expect(page.locator('#observacao summary')).toBeFocused();
 await page.screenshot({path:'.runtime/quality/probe-details.png',fullPage:true});
 const contrast=await page.evaluate(()=>{const L=c=>c.map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4}).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);const ratio=(a,b)=>(Math.max(L(a),L(b))+.05)/(Math.min(L(a),L(b))+.05);const a=document.querySelector('.button.secondary'),s=getComputedStyle(a),rgb=s.borderColor.match(/\d+/g).map(Number),alpha=Number(s.opacity);return {secondaryButtonBoundary:ratio(rgb.map(v=>v*alpha+255*(1-alpha)),[255,255,255]),focusOnWhite:ratio([21,90,203],[255,255,255]),focusOnCanvas:ratio([21,90,203],[237,241,246]),navigationSelectedLine:ratio([144,184,255],[41,69,103])};});
 for(const v of Object.values(contrast))expect(v).toBeGreaterThanOrEqual(3);
 const out={checkedAt:new Date().toISOString(),originalActionAvailableByExpansion:true,probeDetailsFocusOnDocumentLoad:true,nonTextContrast:contrast,scope:'Explicit essential boundary/focus/selection colors, with button opacity; not every decorative separator'};
 fs.writeFileSync('.runtime/quality/disclosure-review.json',JSON.stringify(out,null,2));console.log(out);
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exit(1)});
