// Browser interception only: these fixtures are never published as market data.
const assert=require('node:assert/strict');const {spawn}=require('node:child_process');const {chromium}=require('playwright');
const server=spawn('python3',['-m','http.server','8791','--bind','127.0.0.1','--directory','site'],{stdio:'ignore'});
const fixture={schema_version:1,status:'partial',mode:'latest',generated_at:new Date().toISOString(),briefing_date:'2026-10-27',cutoff_at:new Date().toISOString(),
 markets:[{symbol:'^SOX',name:'純測試費半',group:'美股',status:'ok',close:101,change:1,change_pct:1,session_date:'2026-10-26',previous_session_date:'2026-10-23',quoted_at:'2026-10-26T20:00:00Z',source:'測試來源',source_url:'https://example.org/quote',data_url:'https://example.org/data'}],
 futures:{status:'ok',rows:[{contract:'TX',contract_month:'202611',session:'盤後',trading_date:'2026-10-26',last:24100,open:24000,high:24200,low:23900,volume:500,open_interest:1000,source:'純測試期貨來源（非即時）',source_url:'https://example.org/futures'}]},
 news:{'台灣':[{title:'<img src=x onerror=alert(1)> 純測試半導體新聞',url:'https://example.org/news',publisher:'測試媒體',published_at:'2026-10-26T22:00:00Z',relevance_tags:['半導體／權值股']}],'國際':[]},
 feeds:[{source:'測試RSS',status:'ok',url:'https://example.org/rss'}],notes:['純測試：不冒充即時、不預測漲跌']};
(async()=>{let browser;try{
 for(let i=0;i<30;i++){try{if((await fetch('http://127.0.0.1:8791')).ok)break}catch{}await new Promise(r=>setTimeout(r,100));}
 browser=await chromium.launch({executablePath:require('node:fs').existsSync('/usr/bin/chromium')?'/usr/bin/chromium':undefined,args:['--no-sandbox']});
 for(const width of [320,390,1280]){
  const p=await browser.newPage({viewport:{width,height:844}});const errors=[];p.on('pageerror',e=>errors.push(String(e)));
  await p.route('**/premarket.json',r=>r.fulfill({contentType:'application/json',body:JSON.stringify(fixture)}));
  let publishedCalls=0,newResult=false;
  await p.route('**/premarket.json',r=>{publishedCalls++;return r.fulfill({contentType:'application/json',body:JSON.stringify({...fixture,generated_at:newResult?new Date(Date.now()+1000).toISOString():fixture.generated_at})});});
  await p.goto('http://127.0.0.1:8791/premarket.html');await p.locator('#indices .market-tile').waitFor();
  assert.match(await p.locator('#refresh-status').innerText(),/沒有外部後端帳號需求/);
  assert.match(await p.locator('#collect-now').getAttribute('href'),/github.com.*premarket.yml/);
  assert.match(await p.locator('#futures-data').innerText(),/盤後/);assert.match(await p.locator('#futures-data').innerText(),/非即時/);
  assert.equal(await p.locator('#taiwan-news img').count(),0);assert.match(await p.locator('#taiwan-news').innerText(),/測試媒體/);
  assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await p.locator('#reload-published').click();await p.waitForFunction(()=>document.querySelector('#refresh-status').textContent.includes('沒有啟動新的來源收集'));
  await p.clock.install();
  await p.evaluate(()=>document.querySelector('#collect-now').addEventListener('click',e=>e.preventDefault()));
  const before=publishedCalls;
  await p.locator('#collect-now').click();assert.match(await p.locator('#refresh-status').innerText(),/Run workflow/);assert.equal(publishedCalls,before);
  newResult=true;await p.clock.runFor(15001);
  await p.waitForFunction(()=>document.querySelector('#refresh-status').textContent.includes('已收到新發布結果'));
  assert.ok(publishedCalls>before);
  await p.route('**/premarket.json',r=>r.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'source test unavailable'})}));
  await p.locator('#reload-published').click();await p.waitForFunction(()=>document.querySelector('#brief-status').textContent.includes('source test unavailable'));
  assert.equal(await p.locator('#indices .market-tile').count(),0);assert.equal(await p.locator('#futures-data .market-tile').count(),0);
  assert.deepEqual(errors,[]);await p.close();
 }
 console.log('PASS premarket mobile/desktop: GitHub-only refresh, explicit manual collection, new-result polling, attributed news, futures sessions, source failure clears old values');
}finally{if(browser)await browser.close();server.kill();}})().catch(e=>{console.error(e);process.exitCode=1;});
