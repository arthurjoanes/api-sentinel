const {chromium} = require(process.env.PLAYWRIGHT_MODULE || '@playwright/test');
const fs = require('fs');
(async()=>{
 const browser = await chromium.launch({headless:true,channel:'msedge'});
 const page=await browser.newPage();
 const checks=[];
 for(const width of [1920,1440,768,390,320]){
  await page.setViewportSize({width,height:1000});
  for(const route of ['/','/incidents/2','/incidents/3','/runbooks','/runbooks/erp','/__review/stale','/__review/failure','/__review/empty']){
   await page.goto('http://127.0.0.1:9818'+route);
   const check=await page.evaluate(()=>{
    const rgb=v=>v.match(/[\d.]+/g).map(Number);
    const luminance=c=>c.slice(0,3).map(n=>{n/=255;return n<=.04045?n/12.92:((n+.055)/1.055)**2.4}).reduce((s,n,i)=>s+n*[.2126,.7152,.0722][i],0);
    const background=el=>{while(el){const c=rgb(getComputedStyle(el).backgroundColor);if(c.length<4||c[3]===1)return c;el=el.parentElement;}return [255,255,255]};
    const failures=[];let tested=0;let minimum=99;
    for(const el of document.querySelectorAll('body *')){
     if(!Array.from(el.childNodes).some(n=>n.nodeType===Node.TEXT_NODE&&n.textContent.trim()))continue;
     if(!el.checkVisibility({checkOpacity:true,checkVisibilityCSS:true}))continue;
     const style=getComputedStyle(el), fg=rgb(style.color), bg=background(el);
     let layer=el; while(layer){const opacity=Number(getComputedStyle(layer).opacity);if(opacity<1){const outer=background(layer.parentElement);for(let i=0;i<3;i++){fg[i]=fg[i]*opacity+outer[i]*(1-opacity);bg[i]=bg[i]*opacity+outer[i]*(1-opacity);}}layer=layer.parentElement;}
     const x=luminance(fg),y=luminance(bg),ratio=(Math.max(x,y)+.05)/(Math.min(x,y)+.05);
     const large=parseFloat(style.fontSize)>=24||(parseFloat(style.fontSize)>=18.66&&parseInt(style.fontWeight)>=700);
     minimum=Math.min(minimum,ratio);tested++;
     if(ratio<(large?3:4.5))failures.push({tag:el.tagName,class:el.className,text:el.textContent.trim().slice(0,70),ratio:Math.round(ratio*100)/100,required:large?3:4.5});
    }
    const brand=document.querySelector('.brand').getBoundingClientRect();
    const main=document.querySelector('main');
    const axis=main.getBoundingClientRect().left+parseFloat(getComputedStyle(main).paddingLeft);
    return {tested,minimum:Math.round(minimum*100)/100,failures,brandMainAxisDifference:Math.abs(brand.left-axis)};
   });
   checks.push({width,route,...check});
  }
 }
 fs.writeFileSync('.runtime/art-review/visual-audit.json',JSON.stringify({scope:'Computed text/background contrast and alignment; not a full WCAG audit',checks},null,2));
 const failures=checks.filter(c=>c.failures.length||c.brandMainAxisDifference>1);
 console.log(JSON.stringify({combinations:checks.length,failures},null,2));
 await browser.close();if(failures.length)process.exitCode=1;
})();
