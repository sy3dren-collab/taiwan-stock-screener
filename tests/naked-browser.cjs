const assert=require('node:assert/strict');const {spawn}=require('node:child_process');const {chromium}=require('playwright');
const server=spawn('python3',['-m','http.server','8766','--bind','127.0.0.1','--directory','site'],{stdio:'ignore'});const pause=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{let browser;try{
 for(let i=0;i<40;i++){try{if((await fetch('http://127.0.0.1:8766')).ok)break}catch{}await pause(100)}
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||(require('node:fs').existsSync('/usr/bin/chromium')?'/usr/bin/chromium':undefined),args:['--no-sandbox']});
 for(const width of [320,390,1280]){
  const p=await browser.newPage({viewport:{width,height:844},isMobile:width<500,hasTouch:width<500});const errors=[];p.on('pageerror',e=>errors.push(String(e)));
  await p.goto('http://127.0.0.1:8766');await p.locator('.naked-candidate').first().waitFor();
  assert.equal(await p.locator('.naked-candidate').count(),1);assert.match(await p.locator('#naked-active').innerText(),/尚無通過驗證/);
  const snapshot=JSON.parse(require('node:fs').readFileSync('site/results.json','utf8'));
  await p.waitForFunction(()=>document.querySelector('#as-of').textContent!=='—');
  assert.equal(snapshot.candidates.length,0);assert.equal(snapshot.orders_enabled,false);
  assert.equal(await p.locator('.stock-card').count(),snapshot.watchlist?.candidates.length||0);
  if(snapshot.watchlist?.candidates.length){
    assert.match(await p.locator('#status').innerText(),/研究觀察名單/);
    assert.match(await p.locator('#status').innerText(),/不是進場訊號/);
    assert.equal(snapshot.watchlist.candidates.every(s=>s.observation_only),true);
  }
  assert.equal(await p.locator('#naked-charts svg').count(),0);
  assert.match(await p.locator('#optimization-history').innerText(),/未捏造/);
  await p.locator('.run-entry').first().waitFor();assert.equal(await p.locator('.naked-candidate').filter({hasText:'F｜'}).count(),1);
  await p.locator('.run-entry summary').first().click();
  const latest=JSON.parse(require('node:fs').readFileSync('site/research-history.json','utf8')).runs[0];
  if(!latest.trials.length)assert.match(await p.locator('#run-history').innerText(),/不是0%/);
  else{assert.equal(await p.locator('.run-entry').first().locator('table tr').count(),latest.trials.length+1);if(latest.command==='annual-research')assert.match(await p.locator('.run-entry').first().innerText(),/一年帳戶淨報酬/);}
assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  if(width===390)await p.screenshot({path:'/tmp/naked-research-mobile.png',fullPage:true});
  await p.locator('#legacy-research summary').first().click();assert.equal(await p.locator('.research-card').count(),3);
  assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  // Errors must remove claims, charts and candidates, including after a reload.
  await p.route('**/research.json',route=>route.fulfill({status:503,body:'unavailable'}));await p.reload();await p.locator('#naked-active.error').waitFor();
  assert.match(await p.locator('#naked-active').innerText(),/HTTP 503/);assert.equal(await p.locator('.naked-candidate').count(),0);assert.equal(await p.locator('#naked-charts svg').count(),0);
  assert.deepEqual(errors,[]);await p.close();
 }
 console.log('PASS naked mobile 320/390 and desktop: no unverified recommendations, one focused strategy and result history, archive, no fake charts, source/report errors');
}finally{if(browser)await browser.close();server.kill()}})().catch(e=>{console.error(e);process.exitCode=1});
