'use strict';
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const fmt=n=>Number(n).toLocaleString('zh-TW',{maximumFractionDigits:2});
const when=s=>new Date(s).toLocaleString('zh-TW',{timeZone:'Asia/Taipei',hour12:false});
let apiBase=null;
function link(text,url){const parsed=new URL(url);if(!['https:','http:'].includes(parsed.protocol))throw Error('來源連結格式錯誤');const a=el('a',text);a.href=parsed.href;a.target='_blank';a.rel='noopener noreferrer';return a;}
function news(items,target){const root=document.querySelector(target);root.replaceChildren();if(!items.length){root.append(el('p','截止時間前48小時內，未取得可列示的相關新聞；請查看來源狀態。'));return;}for(const item of items){const card=el('article',undefined,'news-item');card.append(link(item.title,item.url),el('p',`${item.publisher}｜${when(item.published_at)}（台北）`));if(item.relevance_tags?.length)card.append(el('p',item.relevance_tags.join(' · ')));root.append(card);}}
function render(data){
  if(data.schema_version!==1||!Array.isArray(data.markets)||!data.news||!Array.isArray(data.feeds))throw Error('資料格式不完整');
  const status=document.querySelector('#brief-status');status.replaceChildren();
  const today=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  const stale=data.briefing_date!==today;
  status.className=`notice ${data.status==='error'?'error':data.status!=='ok'||stale?'warning':''}`;
  status.append(el('strong',`${data.briefing_date} ${data.mode==='latest'?'最新市場整理':'盤前整理'}${stale?'｜歷史資料，並非今日更新':''}`),el('p',`產生：${when(data.generated_at)}｜資料截止：${when(data.cutoff_at)}（台北）`));
  if(data.status!=='ok')status.append(el('p','部分或全部來源未成功取得，以下逐項標示；缺漏不代表市場沒有變動或沒有新聞。'));
  const indices=document.querySelector('#indices');indices.replaceChildren();
  const priority=['^SOX','^IXIC','TSM','^GSPC','^DJI','^VIX','TWD=X','^TNX','^TWII'];
  const order=m=>priority.includes(m.symbol)?priority.indexOf(m.symbol):priority.length;
  for(const m of [...data.markets].sort((a,b)=>order(a)-order(b))){const card=el('article',undefined,`market-tile ${m.status}`);card.append(el('p',m.group,'market-meta'),el('h3',m.name));
    if(m.status==='error'){card.append(el('p',`無法取得：${m.error}`));}
    else{
      if(![m.close,m.change,m.change_pct].every(Number.isFinite))throw Error('行情數字不合法');
      const cls=m.change>0?'up':m.change<0?'down':'';
      card.append(el('strong',fmt(m.close)+(m.unit?' '+m.unit:''),`market-value ${cls}`),el('p',`${m.change>0?'+':''}${fmt(m.change)}（${m.change_pct>0?'+':''}${fmt(m.change_pct)}%）`,cls),el('p',`${m.quote_type||'收盤'}｜${m.session_date}｜前次 ${m.previous_session_date}${m.quoted_at?'｜報價 '+when(m.quoted_at)+'（台北）':''}`,'market-meta'),link(m.source,m.source_url));
      if(m.warning)card.append(el('p',m.warning));
    }if(m.data_url)card.append(el('p',''),link('來源原始資料',m.data_url));indices.append(card);
  }
  const futures=document.querySelector('#futures-data');futures.replaceChildren();if(data.futures?.warning)futures.append(el('p',data.futures.warning));
  if(['ok','stale'].includes(data.futures?.status)&&data.futures.rows?.length){for(const f of data.futures.rows){const card=el('article',undefined,'market-tile');card.append(el('h3',`${f.contract} ${f.contract_month}｜${f.session}`));if(!Number.isFinite(f.last))throw Error('期貨價格不合法');card.append(el('strong',fmt(f.last),'market-value'),el('p',`報表交易日 ${f.trading_date}（非即時）`),el('p',`開 ${f.open===null?'—':fmt(f.open)}｜高 ${f.high===null?'—':fmt(f.high)}｜低 ${f.low===null?'—':fmt(f.low)}`),el('p',`成交量 ${f.volume===null?'—':fmt(f.volume)}｜未平倉 ${f.open_interest===null?'—':fmt(f.open_interest)}`),link(f.source,f.source_url));futures.append(card);}}
  else futures.append(el('p',`尚無可列示的期交所日／夜盤報表：${data.futures?.error||'此份資料尚未包含期貨來源'}。請使用官方行情連結核對。`));
  news(data.news['台灣'],'#taiwan-news');news(data.news['國際'],'#world-news');
  const sources=document.querySelector('#source-status');sources.replaceChildren();
  for(const f of data.feeds){const p=el('p',`${f.source}｜${f.status==='ok'?'成功':f.status==='empty'?'無符合範圍的相關新聞':'失敗'}${f.error?'：'+f.error:''} `);p.append(link('RSS 來源',f.url));sources.append(p);}
  document.querySelector('#brief-notes').replaceChildren(...data.notes.map(n=>el('li',n)));
}
async function retrieve(url){const response=await fetch(url,{cache:'no-store',signal:AbortSignal.timeout(60000)});const data=await response.json();if(!response.ok&&!data.schema_version)throw Error(data.error||`HTTP ${response.status}`);render(data);return data;}
function showFailure(error){document.querySelector('#brief-status').className='notice error';document.querySelector('#brief-status').textContent=`本次收集失敗：${error.message}；未以舊行情冒充更新結果。`;for(const id of ['indices','futures-data','taiwan-news','world-news'])document.getElementById(id).replaceChildren();}
document.querySelector('#collect-now').addEventListener('click',async()=>{
  if(!apiBase)return;const button=document.querySelector('#collect-now');button.disabled=true;
  document.querySelector('#refresh-status').textContent='正在向原始來源收集，請稍候…';
  try{const data=await retrieve(apiBase+'/api/brief');document.querySelector('#refresh-status').textContent=data.cache_status==='hit'?`使用120秒內共用收集結果，產生時間 ${when(data.generated_at)}；不是本次重新抓取。`:`本次收集已完成（${data.status==='ok'?'各來源成功':'部分來源失敗，請查看提示'}），時間 ${when(data.generated_at)}。`;}
  catch(error){showFailure(error);document.querySelector('#refresh-status').textContent='即時服務未完成本次收集；請核對來源或服務狀態。';}finally{button.disabled=false;}
});
document.querySelector('#reload-published').addEventListener('click',()=>retrieve('premarket.json').catch(showFailure));
(async()=>{
  try{const r=await fetch('premarket-config.json',{cache:'no-store'});if(!r.ok)throw Error('設定檔無法讀取');const config=await r.json();if(config.api_base_url){const u=new URL(config.api_base_url);if(u.protocol!=='https:'||u.username||u.password)throw Error('後端網址需為不含密碼的HTTPS網址');apiBase=u.origin;document.querySelector('#collect-now').disabled=false;document.querySelector('#refresh-status').textContent='已連接收集服務。按一次開始；來源報價可能延遲，120秒內共用收集快取。';}else document.querySelector('#refresh-status').textContent='即時收集尚未啟用：等待連接免費後端帳號。按鈕暫停使用，以下只讀取已發布資料。';}
  catch(error){document.querySelector('#refresh-status').textContent='即時服務尚未就緒：'+error.message;}
  await retrieve('premarket.json').catch(showFailure);
})();
