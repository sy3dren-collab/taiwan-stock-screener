// Fixtures exist only in browser request interception, never in published reports.
const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const {chromium}=require('playwright');
const server=spawn('python3',['-m','http.server','8767','--bind','127.0.0.1','--directory','site'],{stdio:'ignore'});
const pause=ms=>new Promise(r=>setTimeout(r,ms));
const fixture={schema_version:1,research_model_id:'F',classification:'retrospective_diagnostic',promotion_allowed:false,status:'completed',
 period:{trading_sessions:242},entry_cutoff:'2026-09-17',data_quality:{source_proofs:808,warmup_sessions:130,limitations:['測試：非獨立樣本外；正式策略停用']},signal_funnel:{quoted:10000,admitted:3000,signals:1},
 strategy:{start:'2025-10-17',end:'2026-10-16',equity_curve:[{date:'2025-10-16',equity:1000000},{date:'2026-10-16',equity:999000}],
 metrics:{closed_count:1,win_rate:0,net_return:-.001,max_drawdown:.001,profit_factor:0,winners:0,losers:1,total_costs:1000,average_holding_sessions:20,sample_warning:'測試：樣本不足',drawdown_curve:[{date:'2025-10-16',drawdown:0},{date:'2026-10-16',drawdown:.001}],monthly:[{period:'2026-10',net_return:-.001}]},
 closed_trades:[{entry_code:'2330',name:'純測試',signal_date:'2026-09-16',entry_date:'2026-09-17',exit_date:'2026-10-15',net_pnl:-1000,exit_reason:'測試到期'}]}};
(async()=>{let browser;try{
 for(let i=0;i<40;i++){try{if((await fetch('http://127.0.0.1:8767')).ok)break}catch{}await pause(100)}
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||(require('node:fs').existsSync('/usr/bin/chromium')?'/usr/bin/chromium':undefined),args:['--no-sandbox']});
 for(const width of [320,390,1280]){
  const p=await browser.newPage({viewport:{width,height:844},isMobile:width<500});const errors=[];p.on('pageerror',e=>errors.push(String(e)));
  await p.route('**/annual-backtest.json',route=>route.fulfill({contentType:'application/json',body:JSON.stringify(fixture)}));
  await p.goto('http://127.0.0.1:8767');await p.waitForFunction(()=>document.querySelector('#annual-status').textContent.includes('一年回溯研究已完成'));
  assert.match(await p.locator('#annual-metrics').innerText(),/-0\.10%/);assert.match(await p.locator('#annual-metrics').innerText(),/0\.00%/);
  assert.match(await p.locator('#annual-status').innerText(),/正式策略仍未啟用/);
  await p.locator('#annual-detail summary').click();assert.equal(await p.locator('#annual-charts svg').count(),2);assert.match(await p.locator('#annual-charts').innerText(),/2330/);
  assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  const empty=structuredClone(fixture);empty.strategy.closed_trades=[];Object.assign(empty.strategy.metrics,{closed_count:0,win_rate:null,net_return:0,winners:0,losers:0});
  await p.route('**/annual-backtest.json',route=>route.fulfill({contentType:'application/json',body:JSON.stringify(empty)}));await p.reload();await p.waitForFunction(()=>document.querySelector('#annual-metrics').textContent.includes('沒有已完成交易'));
  assert.match(await p.locator('#annual-metrics').innerText(),/勝率為 —/);
  await p.route('**/annual-backtest.json',route=>route.fulfill({status:503,body:'source unavailable'}));await p.reload();await p.locator('#annual-status.error').waitFor();
  assert.equal(await p.locator('#annual-metrics table').count(),0);assert.equal(await p.locator('#annual-charts svg').count(),0);assert.match(await p.locator('#annual-status').innerText(),/503/);
  assert.deepEqual(errors,[]);await p.close();
 }
 console.log('PASS annual research mobile 320/390 and desktop: real-loss metrics, inactive formal strategy, full trades, zero trades, source errors');
}finally{if(browser)await browser.close();server.kill()}})().catch(e=>{console.error(e);process.exitCode=1});
