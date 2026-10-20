const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const {chromium}=require('playwright');
const server=spawn('python3',['-m','http.server','8771','--bind','127.0.0.1','--directory','site'],{stdio:'ignore'});
(async()=>{let browser;try{
 for(let i=0;i<30;i++){try{if((await fetch('http://127.0.0.1:8771')).ok)break}catch{}await new Promise(r=>setTimeout(r,100))}
 browser=await chromium.launch({executablePath:require('node:fs').existsSync('/usr/bin/chromium')?'/usr/bin/chromium':undefined,args:['--no-sandbox']});
 for(const width of [320,390,1280]){
  const p=await browser.newPage({viewport:{width,height:844}});
  await p.goto('http://127.0.0.1:8771');
  await p.waitForFunction(()=>document.querySelector('#fast-results').textContent.includes('總耗時'));
  assert.match(await p.locator('#fast-results').innerText(),/未執行一年回測|只對最佳/);
  assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await p.close();
 }
 console.log('PASS fast report at mobile 320/390 and desktop; gate visible, no overflow');
}finally{if(browser)await browser.close();server.kill();}})().catch(e=>{console.error(e);process.exitCode=1});
