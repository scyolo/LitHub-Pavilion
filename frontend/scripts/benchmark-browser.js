async page => {
 const target=new URL(page.url()),cpu=Number(target.searchParams.get('cpu')||1),base=target.origin+target.pathname;
 const cases=[['home','/'],['browse','/papers'],['broad-learning','/papers?q=learning'],['rare-and','/papers?q=speculative%20decoding'],['scoped-learning','/papers?q=learning&venue=ICML&year=2025'],['fuzzy','/papers?q=speculativ%20decodng'],['exact','/papers?match=exact&q='+encodeURIComponent('EESMR: Energy Efficient BFT---SMR for the masses')]];
 const browser=page.context().browser(),report={date:new Date().toISOString(),base,main_thread_cpu_throttle:cpu,network_label:target.searchParams.get('network')||'unthrottled local production preview',cases:[]};
 for(const [name,hash] of cases){
  const context=await browser.newContext({viewport:cpu>1?{width:390,height:844}:{width:1440,height:1000}}),p=await context.newPage(),events=[],pending=[],errors=[];
  context.on('requestfinished',request=>{pending.push((async()=>events.push({url:request.url(),...await request.sizes().catch(()=>({}))}))());});p.on('pageerror',e=>errors.push(e.message));
  if(cpu>1){const cdp=await context.newCDPSession(p);await cdp.send('Emulation.setCPUThrottlingRate',{rate:cpu});}
  await p.addInitScript(()=>{window.__vitals={cls:0};new PerformanceObserver(list=>{for(const e of list.getEntries())window.__vitals.lcp=e.startTime;}).observe({type:'largest-contentful-paint',buffered:true});new PerformanceObserver(list=>{for(const e of list.getEntries())if(!e.hadRecentInput)window.__vitals.cls+=e.value;}).observe({type:'layout-shift',buffered:true});});
  const start=Date.now();await p.goto(base+'#'+hash,{waitUntil:'domcontentloaded'});
  let failure=null;try{await p.waitForFunction(home=>home?/^[\d,]+$/.test(document.querySelector('.metric-value')?.textContent||''):document.querySelector('.explorer-results')?.getAttribute('aria-busy')==='false'&&/[\d,]+ 篇论文/.test(document.querySelector('.results-toolbar strong')?.textContent||''),name==='home',{timeout:16000});}catch(error){failure=error.message;}
  const ready=Date.now()-start;await p.waitForLoadState('networkidle',{timeout:5000}).catch(()=>{});const metrics=await p.evaluate(()=>({fcp:performance.getEntriesByName('first-contentful-paint')[0]?.startTime,lcp:window.__vitals.lcp,cls:window.__vitals.cls,ttfb:performance.getEntriesByType('navigation')[0]?.responseStart,home:performance.getEntriesByName('lithub-home-ready')[0]?.startTime,total:document.querySelector('.results-toolbar strong')?.textContent||document.querySelector('.metric-value')?.textContent,cards:document.querySelectorAll('.paper-card').length,overflow:document.documentElement.scrollWidth>innerWidth}));
  await Promise.all(pending);
  const network={requests:events.length,body_bytes:events.reduce((s,e)=>s+(e.responseBodySize||0),0),card_shards:events.filter(e=>e.url.includes('/browse-')).length,detail_shards:events.filter(e=>/\/(papers|compressed)-/.test(e.url)).length};
  let warm=null;if(!failure){
   if(name==='home'){
    await context.route('**/manifest.json',async route=>{await new Promise(resolve=>setTimeout(resolve,5000));await route.continue().catch(()=>{});});
    const start=Date.now();await p.reload({waitUntil:'domcontentloaded'});await p.locator('.metric-value').first().waitFor();warm=Date.now()-start;
   }else{
    await p.goto(base+'#/');await p.locator('.metric-value').first().waitFor();const start=Date.now();await p.goto(base+'#'+hash);await p.waitForFunction(()=>document.querySelector('.explorer-results')?.getAttribute('aria-busy')==='false'&&/[\d,]+ 篇论文/.test(document.querySelector('.results-toolbar strong')?.textContent||''));warm=Date.now()-start;
   }
  }
  report.cases.push({name,ready_ms:ready,warm_ms:warm,...metrics,...network,errors,failure});
  if(name==='broad-learning'&&cpu>1)await p.screenshot({animations:'disabled',path:'output/playwright/limited-network-mobile-search.png'});
  await context.close();
 }
 report.budgets={home_ms:cpu>1?2500:1000,search_cold_ms:cpu>1?6500:1500,search_warm_ms:cpu>1?800:250,home_warm_ms:cpu>1?1500:500};
 report.passed=report.cases.every(r=>!r.failure&&!r.errors.length&&!r.overflow&&r.ready_ms<=(r.name==='home'?report.budgets.home_ms:report.budgets.search_cold_ms)&&r.warm_ms<=(r.name==='home'?report.budgets.home_warm_ms:report.budgets.search_warm_ms));
 return report;
}