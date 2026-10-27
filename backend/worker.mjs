// Public read-only collector. Deploy only under Workers Free; no paid bindings.
import sources from '../market_sources.json' with {type:'json'};
const CACHE_SECONDS=120;
export const FUTURES_URL='https://openapi.taifex.com.tw/v1/DailyMarketReportFut';
const formatters=new Map();
const zonedDate=(stamp,tz)=>{if(!formatters.has(tz))formatters.set(tz,new Intl.DateTimeFormat('en-CA',{timeZone:tz,year:'numeric',month:'2-digit',day:'2-digit'}));return formatters.get(tz).format(new Date(stamp));};
const iso=stamp=>new Date(stamp).toISOString();
const clean=value=>String(value||'').replace(/<[^>]*>/g,'').replace(/\s+/g,' ').trim();
export function safeUrl(url){const u=new URL(url);if(!['http:','https:'].includes(u.protocol)||u.username||u.password)throw Error('無效來源連結');return u.href;}
const decode=value=>clean(value.replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g,'$1').replace(/&#(x[0-9a-f]+|\d+);/gi,(_,n)=>{const point=n[0].toLowerCase()==='x'?parseInt(n.slice(1),16):Number(n);return point>=0&&point<=0x10ffff?String.fromCodePoint(point):'';}).replace(/&amp;/g,'&').replace(/&quot;/g,'"').replace(/&apos;/g,"'").replace(/&lt;/g,'<').replace(/&gt;/g,'>'));
const THEMES=[['半導體／權值股',/台積電|半導體|晶片|輝達|鴻海|聯發科|tsmc|semiconductor|nvidia|chip|apple|micron/i],['央行／重要經濟數據',/央行|利率|通膨|非農|就業|聯準會|cpi|pce|fomc|federal reserve|inflation|interest rate|payroll|gdp|jobs/i],['地緣／政策風險',/戰爭|關稅|台海|制裁|中東|石油|油價|地震|颱風|war|tariff|sanction|iran|israel|ukraine|earthquake/i],['股匯市／資金',/台指|台股|期貨|外資|美股|股市|新台幣|匯率|美元|stocks|markets|dollar|treasury|yields/i]];
export const tags=title=>THEMES.filter(([,pattern])=>pattern.test(title)).map(([name])=>name);

export function parseQuote(payload,market,now){
  const [symbol,name,group,tz]=market;const chart=payload.chart;
  if(chart?.error||!chart?.result?.length)throw Error('來源沒有有效行情');
  const item=chart.result[0],meta=item.meta;
  if(meta.symbol!==symbol)throw Error('來源代號不符');
  const value=meta.regularMarketPrice,stamp=meta.regularMarketTime*1000;
  if(!Number.isFinite(value)||value<=0||!Number.isFinite(stamp)||stamp>now)throw Error('報價或報價時間不合法');
  const dates=item.timestamp||[],closes=item.indicators?.quote?.[0]?.close||[];
  if(dates.length!==closes.length)throw Error('價格與日期筆數不符');
  const day=zonedDate(stamp,tz);
  const prior=dates.map((d,i)=>({day:zonedDate(d*1000,tz),value:closes[i]})).filter(x=>x.day<day&&Number.isFinite(x.value)&&x.value>0).sort((a,b)=>a.day.localeCompare(b.day)).at(-1);
  if(!prior)throw Error('沒有可驗證的前次收盤');
  const stale=now-stamp>4*86400000;
  return {symbol,name,group,status:stale?'stale':'ok',close:value,previous_close:prior.value,
    change:value-prior.value,change_pct:(value/prior.value-1)*100,
    session_date:day,previous_session_date:prior.day,quoted_at:iso(stamp),quote_type:'來源最新報價（可能延遲）',
    exchange_timezone:tz,currency:meta.currency,unit:symbol==='^TNX'?'%（殖利率指標）':symbol==='TWD=X'?'新台幣／美元':'',
    source:'Yahoo Finance 公開行情（非交易所逐筆即時）',source_url:'https://finance.yahoo.com/quote/'+encodeURIComponent(symbol)+'/',
    warning:stale?'報價超過4天，請核對休市與來源狀態':null};
}

export function parseNews(xml,source,category,now){
  if(/<!DOCTYPE|<!ENTITY/i.test(xml)||!/<rss\b/i.test(xml))throw Error('來源不是可接受的 RSS');
  const items=[];
  for(const match of xml.matchAll(/<item\b[^>]*>([\s\S]*?)<\/item>/gi)){
    const get=tag=>{const found=match[1].match(new RegExp('<'+tag+'(?:\\s[^>]*)?>([\\s\\S]*?)</'+tag+'>','i'));return found?decode(found[1]):'';};
    const title=get('title'),published=Date.parse(get('pubDate'));
    if(!title||!Number.isFinite(published)||published>now||now-published>48*3600000)continue;
    const relevant=tags(title);if(!relevant.length)continue;
    items.push({title,url:safeUrl(get('link')),publisher:get('source')||source,feed_source:source,category,published_at:iso(published),relevance_tags:relevant});
    if(items.length>=40)break;
  }return items;
}

function numeric(value){if(value===undefined||value===null||['','-','--'].includes(String(value).trim()))return null;const text=String(value).replace(/,/g,'').replace(/%$/,'').trim();if(!/^[+-]?\d+(\.\d+)?$/.test(text))throw Error('期貨報表數字不合法');return Number(text);}
export function parseFutures(rows,now){
  if(!Array.isArray(rows))throw Error('期交所回應不是資料列');
  let selected=rows.filter(r=>r.Contract==='TX'&&/^\d{6}$/.test(r.ContractMonth||''));
  const dates=selected.map(r=>String(r.Date||r.TradingDate||''));
  if(dates.some(d=>!/^\d{8}$/.test(d)))throw Error('期貨交易日期格式待確認');
  const latest=dates.sort().at(-1);selected=selected.filter(r=>String(r.Date||r.TradingDate)===latest);
  if(!selected.length)throw Error('沒有可驗證的 TX 月合約資料，請查看官方行情');
  const contracts=[...new Set(selected.map(r=>r.ContractMonth))].sort().slice(0,2);
  return selected.filter(r=>contracts.includes(r.ContractMonth)).map(r=>{
    const date=String(r.Date||r.TradingDate||'');if(!/^\d{8}$/.test(date))throw Error('期貨交易日期格式待確認');
    const day=date.slice(0,4)+'-'+date.slice(4,6)+'-'+date.slice(6,8);
    if(Date.parse(day+'T00:00:00+08:00')>now)throw Error('期貨報表含未來日期');
    const last=numeric(r.LastPrice);if(last===null||last<=0)throw Error('期貨成交價缺漏');
    return {contract:'TX',contract_month:r.ContractMonth,session:r.TradingSession||'來源未標示，不能推定為日盤或夜盤',
      trading_date:day,last,open:numeric(r.OpeningPrice),high:numeric(r.HighestPrice),low:numeric(r.LowestPrice),
      change:numeric(r.Change),volume:numeric(r.Volume),open_interest:numeric(r.OpenInterest),
      source:'臺灣期貨交易所公開交易報表（非即時報價）',source_url:FUTURES_URL};
  });
}

async function body(url,fetcher){
  const response=await fetcher(url,{headers:{'User-Agent':'TaiwanMarketBrief/1.0'},signal:AbortSignal.timeout(12000)});
  if(!response.ok)throw Error('來源 HTTP '+response.status);
  const reader=response.body.getReader();let size=0;const chunks=[];
  for(;;){const {done,value}=await reader.read();if(done)break;size+=value.byteLength;if(size>700000){await reader.cancel();throw Error('來源回應超過安全大小上限');}chunks.push(value);}
  const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
  return {text:new TextDecoder().decode(bytes),hash};
}

export async function collect(at=null,fetcher=fetch){
  const clock=()=>at??Date.now();const now=clock();
  const markets=await Promise.all(sources.markets.map(async m=>{
    const url='https://query1.finance.yahoo.com/v8/finance/chart/'+encodeURIComponent(m[0])+'?interval=1d&range=10d';
    try{const raw=await body(url,fetcher);return {...parseQuote(JSON.parse(raw.text),m,clock()),data_url:url,payload_sha256:raw.hash};}
    catch(error){return {symbol:m[0],name:m[1],group:m[2],status:'error',error:String(error.message),data_url:url};}
  }));
  const feeds=await Promise.all(sources.feeds.map(async([source,category,url])=>{
    try{const raw=await body(url,fetcher);const items=parseNews(raw.text,source,category,clock());return {source,category,url,status:items.length?'ok':'empty',items,payload_sha256:raw.hash};}
    catch(error){return {source,category,url,status:'error',error:String(error.message),items:[]};}
  }));
  let futures;
  try{const raw=await body(FUTURES_URL,fetcher);const rows=parseFutures(JSON.parse(raw.text),clock());const stale=clock()-Date.parse(rows[0].trading_date+'T00:00:00+08:00')>5*86400000;futures={status:stale?'stale':'ok',rows,warning:stale?'期貨報表超過4個完整日曆日，請核對休市與來源狀態':null,source_url:FUTURES_URL,payload_sha256:raw.hash};}
  catch(error){futures={status:'error',rows:[],error:String(error.message),source_url:FUTURES_URL};}
  const seen=new Set(),news=feeds.flatMap(f=>f.items).sort((a,b)=>b.relevance_tags.length-a.relevance_tags.length||b.published_at.localeCompare(a.published_at)).filter(n=>{const k=n.title.toLowerCase();if(seen.has(k))return false;seen.add(k);return true;});
  const healthy=markets.filter(m=>m.status==='ok').length+feeds.filter(f=>f.status==='ok').length+(futures.status==='ok'?1:0);
  const failures=markets.filter(m=>m.status!=='ok').length+feeds.filter(f=>f.status==='error').length+(futures.status==='error'?1:0);
  return {schema_version:1,mode:'latest',status:healthy?(failures?'partial':'ok'):'error',generated_at:iso(clock()),
    briefing_date:zonedDate(now,'Asia/Taipei'),cutoff_at:iso(clock()),news_window_hours:48,markets,futures,
    feeds:feeds.map(({items,...f})=>f),news:Object.fromEntries(['台灣','國際'].map(c=>[c,news.filter(n=>n.category===c).slice(0,20)])),
    notes:['每次更新收集來源最新可取得資料；120秒內共用快取，報價可能延遲，非逐筆即時行情。',
      '期交所資料為公開交易報表，日盤／夜盤依原始欄位標示；不能當作當下台指期即時價格。月份排序不代表建議交易合約。',
      '新聞依台指期相關主題標記與發布時間整理；不自動推論利多利空，不保證事件已完整收錄。',
      '美國公布時間、日光節約時間與台灣到期／休市請以官方公告為準；沒有可信來源時不填猜測時間。',
      '未提供即時委買賣、成交逐筆、大單或漲跌預測；來源失敗會明示，沒有假資料補值。']};
}

let inflight=null;
export default {
  async fetch(request,env={},ctx={waitUntil(){}}){
    const origin=request.headers.get('Origin'),allowed=env.ALLOWED_ORIGIN||'https://sy3dren-collab.github.io';
    const headers={'Access-Control-Allow-Origin':allowed,'Vary':'Origin','Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'};
    const reply=(data,status=200)=>new Response(JSON.stringify(data),{status,headers});
    if(origin!==allowed)return reply({error:'不允許的網站來源'},403);
    if(request.method==='OPTIONS')return new Response(null,{status:204,headers:{...headers,'Access-Control-Allow-Methods':'GET, OPTIONS'}});
    if(request.method!=='GET')return reply({error:'只提供唯讀更新'},405);
    if(new URL(request.url).pathname!=='/api/brief')return reply({error:'不存在的 API'},404);
    const cache=globalThis.caches?.default;
    const key=new Request(new URL('/_cache/latest-v1',request.url));
    const cached=await cache?.match(key);
    if(cached){const data=await cached.json();return reply({...data,cache_status:'hit',cache_max_age_seconds:CACHE_SECONDS},data.status==='error'?502:200);}
    if(!inflight)inflight=collect().finally(()=>{inflight=null;});
    try{
      const data=await inflight;
      if(cache){const stored=new Response(JSON.stringify(data),{headers:{'Cache-Control':'public, max-age='+ (data.status==='error'?30:CACHE_SECONDS)}});ctx.waitUntil(cache.put(key,stored));}
      return reply({...data,cache_status:'miss',cache_max_age_seconds:CACHE_SECONDS},data.status==='error'?502:200);
    }catch(error){return reply({error:'收集失敗：'+error.message},502);}
  }
};
