const assert=require('node:assert/strict');
(async()=>{
 const {default:worker,parseQuote,parseNews,parseFutures,collect,FUTURES_URL}=await import('../backend/worker.mjs');
 const sources=JSON.parse(require('node:fs').readFileSync('market_sources.json'));
 const now=Date.UTC(2026,9,27,0,10),quote=symbol=>({chart:{result:[{meta:{symbol,regularMarketTime:Date.UTC(2026,9,26,20)/1000,regularMarketPrice:110},timestamp:[Date.UTC(2026,9,23,13,30)/1000,Date.UTC(2026,9,26,13,30)/1000],indicators:{quote:[{close:[100,110]}]}}]}});
 const q=parseQuote(quote('^GSPC'),sources.markets[0],now);assert.equal(q.previous_close,100);assert.ok(Math.abs(q.change_pct-10)<1e-8);assert.match(q.quoted_at,/2026-10-26/);
 assert.throws(()=>parseQuote(quote('WRONG'),sources.markets[0],now),/代號/);
 const xml='<rss><channel><item><title>Fed CPI and TSMC update</title><link>https://example.org/story</link><pubDate>Mon, 26 Oct 2026 20:00:00 GMT</pubDate></item><item><title>Sports update</title><link>https://example.org/sport</link><pubDate>Mon, 26 Oct 2026 20:00:00 GMT</pubDate></item></channel></rss>';
 const news=parseNews(xml,'BBC','國際',now);assert.equal(news.length,1);assert.ok(news[0].relevance_tags.includes('半導體／權值股'));
 assert.throws(()=>parseNews(xml.replace('https://example.org/story','javascript:alert(1)'),'BBC','國際',now),/無效/);
 assert.throws(()=>parseNews('<!DOCTYPE rss><rss/>','BBC','國際',now));
 const row={Date:'20261026',Contract:'TX',ContractMonth:'202611',TradingSession:'盤後',LastPrice:'24,100',OpeningPrice:'24000',HighestPrice:'24150',LowestPrice:'23950',Volume:'500',OpenInterest:'1000',Change:'100'};
 assert.equal(parseFutures([row],now)[0].session,'盤後');assert.equal(parseFutures([row],now)[0].last,24100);
 assert.throws(()=>parseFutures([{...row,LastPrice:'--'}],now),/缺漏/);
 const failed=await collect(now,async()=>{throw Error('offline');});assert.equal(failed.status,'error');assert.equal(failed.markets.some(q=>'close' in q),false);assert.equal(failed.futures.rows.length,0);
 const locked=await collect(now,async()=>new Response('login required',{status:401}));assert.ok(locked.markets.every(m=>m.skip_reason==='requires_login'));assert.ok(locked.feeds.every(f=>f.skip_reason==='requires_login'));assert.equal(locked.futures.skip_reason,'requires_login');
 const paid=await collect(now,async()=>new Response('subscription required',{status:402}));assert.ok(paid.markets.every(m=>m.skip_reason==='requires_payment'));assert.equal(paid.news['台灣'].length,0);
 const origin='https://app.test';assert.equal((await worker.fetch(new Request('https://api.test/api/brief',{headers:{Origin:'https://evil.test'}}),{ALLOWED_ORIGIN:origin})).status,403);
 assert.equal((await worker.fetch(new Request('https://api.test/api/brief',{method:'POST',headers:{Origin:origin}}),{ALLOWED_ORIGIN:origin})).status,405);
 let calls=0;const originalFetch=global.fetch,originalCache=global.caches;const cached=new Map(),pending=[];
 global.caches={default:{match:async key=>cached.get(key.url)?.clone(),put:async(key,value)=>{cached.set(key.url,value.clone());}}};
 global.fetch=async url=>{calls++;const u=String(url);if(u===FUTURES_URL)return new Response(JSON.stringify(row? [row]:[]));if(u.includes('/chart/'))return new Response(JSON.stringify(quote(decodeURIComponent(u.split('/chart/')[1].split('?')[0]))));return new Response(xml);};
 try{
  const request=()=>new Request('https://api.test/api/brief?cachebust='+Math.random(),{headers:{Origin:origin}});
  const first=await worker.fetch(request(),{ALLOWED_ORIGIN:origin},{waitUntil:p=>pending.push(p)});const data=await first.json();assert.equal(data.cache_status,'miss');await Promise.all(pending);
  const count=calls;assert.equal(count,sources.markets.length+sources.feeds.length+1);
  const second=await (await worker.fetch(request(),{ALLOWED_ORIGIN:origin})).json();assert.equal(second.cache_status,'hit');assert.equal(calls,count);assert.equal(second.generated_at,data.generated_at);
 }finally{global.fetch=originalFetch;global.caches=originalCache;}
 console.log('PASS worker: real timestamps, attribution, futures sessions, theme filtering, no fake fallback, CORS, cache reuse');
})().catch(e=>{console.error(e);process.exitCode=1;});
