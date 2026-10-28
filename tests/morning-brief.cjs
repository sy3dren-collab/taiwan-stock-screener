const assert=require('node:assert/strict');
(async()=>{
 const {buildMorningBrief}=await import('../site/brief-summary.mjs');
 const m=(symbol,value,pct,date='2026-10-27')=>({symbol,name:symbol,status:'ok',close:value,change:value*pct/100,change_pct:pct,session_date:date,source_url:'https://example.org/market'});
 const data={generated_at:'2026-10-28T00:00:00Z',briefing_date:'2026-10-28',markets:[m('^SOX',100,2),m('^IXIC',200,1),m('TSM',300,-1),{symbol:'^VIX',status:'stale',close:25,name:'VIX',warning:'stale'}],futures:{status:'ok',rows:[{contract_month:'202611',session:'盤後',trading_date:'2026-10-27',last:24100,high:24200,low:24000}]},news:{'台灣':[{title:'原始標題',description:'來源提供的原始摘要 3.2%。',publisher:'原始媒體',url:'https://example.org/story',relevance_tags:['半導體／權值股']}],'國際':[{title:'只有標題',publisher:'國際媒體',url:'https://example.org/other',relevance_tags:[]}]}};
 const brief=buildMorningBrief(data);
 assert.equal(brief.coverage.quotes_available,3);assert.equal(brief.missing.length,1);
 assert.match(brief.overview.map(x=>x.text).join('\n'),/1 個百分點/);
 assert.equal(brief.futures[0].range_points,200);
 assert.equal(brief.headlines[0].excerpt,data.news['台灣'][0].description);
 assert.equal(brief.headlines[1].excerpt,null);assert.match(brief.headlines[1].summary_kind,/不推測內文/);
 assert.match(brief.calendar.error,/不能推定/);
 const different=buildMorningBrief({...data,markets:[m('^SOX',100,2),m('^IXIC',200,1,'2026-10-26')]});
 assert.equal(different.overview.some(x=>x.text.includes('個百分點')),false);
 const unavailable=buildMorningBrief({markets:[{symbol:'^SOX',name:'SOX',status:'error',error:'unavailable'}],news:{}});
 assert.equal(unavailable.metrics.length,0);assert.match(unavailable.overview[0].text,/無法形成數據概況/);assert.equal(unavailable.headlines.length,0);
 const weekend=buildMorningBrief({...data,briefing_date:'2026-10-31'});assert.match(weekend.session_note,/週末/);
 console.log('PASS morning brief: source-backed calculations, date matching, excerpts without invented summaries, missing-data and weekend handling');
})().catch(e=>{console.error(e);process.exitCode=1;});
