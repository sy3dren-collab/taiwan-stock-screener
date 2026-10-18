'use strict';
const $ = (selector) => document.querySelector(selector);
let data = null;
let market = 'all';
const format = (n, digits = 2) => Number(n).toLocaleString('zh-TW', { maximumFractionDigits: digits });
const ns = 'http://www.w3.org/2000/svg';
function node(tag, className, content) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (content !== undefined) el.textContent = content;
  return el;
}
function svgNode(tag, attrs, content) {
  const el = document.createElementNS(ns, tag);
  Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, String(value)));
  if (content !== undefined) el.textContent = content;
  return el;
}
function chart(stock) {
  const bars = stock.bars.slice(-60);
  const svg = svgNode('svg', {viewBox: '0 0 600 260', role: 'img', 'aria-label': `${stock.name}最近 ${bars.length} 個交易日 K 線及成交量；紅漲綠跌。虛線為支撐。`});
  svg.append(svgNode('title', {}, `${stock.code} ${stock.name} 每日開高低收及成交量`));
  const left = 8, right = 540, top = 12, bottom = 188;
  const min = Math.min(...bars.map(b => b.low), stock.support) * .985;
  const max = Math.max(...bars.map(b => b.high), stock.support) * 1.015;
  const y = price => bottom - (price - min) / (max - min || 1) * (bottom - top);
  const step = (right - left) / bars.length;
  for (let i = 0; i < 4; i++) {
    const value = min + (max - min) * i / 3;
    svg.append(svgNode('line', {x1: left, x2: right, y1: y(value), y2: y(value), stroke: '#edf0eb'}));
    svg.append(svgNode('text', {x: right + 8, y: y(value) + 4, fill: '#7b8882', 'font-size': 11}, format(value)));
  }
  svg.append(svgNode('line', {x1:left, x2:right, y1:y(stock.support), y2:y(stock.support), stroke:'#8a9a79', 'stroke-dasharray':'5 4'}));
  const maxVolume = Math.max(...bars.map(b => b.volume), 1);
  bars.forEach((bar, i) => {
    const x = left + (i + .5) * step;
    const color = bar.close > bar.open ? '#cb4242' : bar.close < bar.open ? '#178367' : '#68766e';
    const group = svgNode('g', {});
    group.append(svgNode('title', {}, `${bar.date} 開 ${bar.open} 高 ${bar.high} 低 ${bar.low} 收 ${bar.close} 量 ${format(bar.volume,0)} 股`));
    group.append(svgNode('line', {x1:x,x2:x,y1:y(bar.high),y2:y(bar.low),stroke:color,'stroke-width':1}));
    group.append(svgNode('rect', {x:x-step*.3,y:Math.min(y(bar.open),y(bar.close)),width:step*.6,height:Math.max(1, Math.abs(y(bar.open)-y(bar.close))),fill:color}));
    const height = bar.volume / maxVolume * 34;
    group.append(svgNode('rect', {x:x-step*.3,y:235-height,width:step*.6,height,fill:color,opacity:.5}));
    svg.append(group);
  });
  [0, Math.floor(bars.length / 2), bars.length - 1].forEach(i => {
    svg.append(svgNode('text', {x:left+(i+.5)*step,y:254,fill:'#7b8882','font-size':10,'text-anchor':i===0?'start':i===bars.length-1?'end':'middle'}, bars[i].date.slice(5)));
  });
  return svg;
}
function card(stock, rank) {
  const el = node('article', 'stock-card');
  const top = node('div', 'stock-top');
  const identity = node('div','stock-identity');
  const heading = node('h3','stock-title');
  heading.append(node('span','stock-code',stock.code),document.createTextNode(' '),node('span','stock-name',stock.name));
  identity.append(node('div','rank',`觀察 ${String(rank).padStart(2,'0')}`),heading);
  const meta = node('div','stock-meta');
  meta.append(node('span','badge',stock.market==='TWSE'?'上市':'上櫃'));
  identity.append(meta);
  const color = stock.change_pct > 0 ? 'up' : stock.change_pct < 0 ? 'down' : '';
  const quote = node('div',`quote ${color}`);
  quote.append(node('strong','',format(stock.close)),node('small','',`${stock.change_pct > 0 ? '+' : ''}${format(stock.change_pct)}% · 收盤`));
  top.append(identity,quote);
  const graph = node('div','chart'); graph.append(chart(stock));
  const caption = node('p','chart-caption');caption.append(node('span','','最近 60 個交易日 · 下方為成交量'),node('span','','┄ 支撐'));
  const levels = node('dl','levels');
  [['支撐價格',stock.support],['參考停損',stock.stop],['參考目標',stock.target],['風險報酬比',`${format(stock.reward_risk)} 倍`]].forEach(([label,value])=>{
    const item=node('div'); item.append(node('dt','',label),node('dd','',typeof value==='number'?format(value,3):value));levels.append(item);
  });
  const reasons = node('ul','reasons');stock.reasons.forEach(reason=>reasons.append(node('li','',reason)));
  const foot = node('div','stock-foot');foot.append(node('span','',`行情 ${stock.date} · 成交量單位：股`),node('span','',`排序分數 ${format(stock.score,1)}`));
  el.append(top,graph,caption,levels,node('p','reason-title','入選依據'),reasons,foot);
  return el;
}
function render() {
  $('#cards').replaceChildren();
  if (!data || data.status !== 'ok') return;
  const query = $('#search').value.trim().toLowerCase();
  const sort = $('#sort').value;
  const stocks = data.candidates.filter(stock=>(market==='all'||stock.market===market)&&`${stock.code} ${stock.name}`.toLowerCase().includes(query));
  stocks.sort((a,b)=>sort==='code'?a.code.localeCompare(b.code):b[sort]-a[sort]||a.code.localeCompare(b.code));
  stocks.forEach((stock,i)=>$('#cards').append(card(stock,i+1)));
  $('#empty').hidden=stocks.length>0;
  $('#empty-message').textContent=data.candidates.length===0?'本次沒有股票符合全部條件。沒有合格標的時，不放寬條件湊數。':'此市場或搜尋條件沒有候選股票，請調整篩選。';
}
const labels = {
  fast_ma:'短期均線（交易日）',slow_ma:'長期均線（交易日）',slope_days:'均線升幅觀察日數',pivot_radius:'確認轉折左右根數',structure_days:'波段結構觀察日數',pullback_days:'回檔量縮觀察日數',volume_baseline_days:'量能基準日數',volume_ratio_max:'回檔均量／基準均量上限',support_distance_max:'支撐距離上限',minimum_pullback:'最小回檔深度',minimum_slope:'短均線最小升幅（須大於）',atr_days:'ATR 計算日數',stop_atr_buffer:'停損 ATR 緩衝倍數',max_risk_fraction:'停損距離／收盤上限',min_reward_risk:'最低風險報酬比',min_average_volume:'最低平均成交股數',max_daily_gap:'單日收盤變動絕對值上限',target_count:'最低目標檔數',max_candidates:'最多候選檔數'
};
function validateResult(result) {
  if (!result || result.schema_version !== 1 || !['ok','error'].includes(result.status) || !Array.isArray(result.candidates)) throw new Error('結果格式不正確');
  if (result.status==='ok') {
    if (!result.as_of || !result.parameters || !Number.isFinite(result.universe_count)) throw new Error('結果缺少行情日期或策略參數');
    for (const s of result.candidates) {
      if (typeof s.code!=='string' || typeof s.name!=='string' || !['TWSE','TPEX'].includes(s.market) || !Array.isArray(s.reasons) || !s.reasons.every(r=>typeof r==='string') || !Array.isArray(s.bars) || s.bars.length<2) throw new Error('候選股票資料不完整');
      for (const k of ['close','change_pct','support','stop','target','reward_risk','score']) if (!Number.isFinite(s[k])) throw new Error('候選股票數值不合法');
      if (s.date!==result.as_of) throw new Error('候選股票行情日期不一致');
      for (const b of s.bars) {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(b.date) || ['open','high','low','close','volume'].some(k=>!Number.isFinite(b[k])) || b.low<=0 || b.low>Math.min(b.open,b.close) || b.high<Math.max(b.open,b.close) || b.volume<0) throw new Error('K 線行情不合法');
      }
    }
  }
  return result;
}
async function load() {
  try {
    const response = await fetch('results.json',{cache:'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    data = validateResult(await response.json());
    $('#updated').textContent=data.generated_at?`產生時間 ${new Date(data.generated_at).toLocaleString('zh-TW',{timeZone:'Asia/Taipei',hour12:false})}（台北）`:'尚未執行資料更新';
    if (data.status !== 'ok') throw new Error((data.errors || []).join('；') || '資料尚未準備完成');
    $('#as-of').textContent=data.as_of;
    $('#count').textContent=data.candidates.length;
    $('#universe').textContent=format(data.universe_count,0);
    const warnings = [...(data.warnings || [])];
    const age = (Date.now()-new Date(`${data.as_of}T00:00:00+08:00`).getTime())/86400000;
    if (age>4) warnings.push('行情日期距今超過 4 天，請確認休市公告與排程是否正常；本頁不是即時報價。');
    $('#status').className=`notice ${warnings.length?'warning':''}`;
    $('#status').replaceChildren(node('p','',`資料截至 ${data.as_of} 收盤。${data.qualified_count} 檔符合策略，顯示前 ${data.candidates.length} 檔。`));
    warnings.forEach(message=>$('#status').append(node('p','',message)));
    const table=node('table','parameter-table');
    const header=node('tr');['條件','設定名稱','本次數值'].forEach(t=>header.append(node('th','',t)));table.append(header);
    Object.entries(data.parameters).forEach(([key,value])=>{const row=node('tr');[labels[key]||key,key,String(value)].forEach(t=>row.append(node('td','',t)));table.append(row);});
    $('#parameters').replaceChildren(table);
    render();
  } catch(error) {
    data=null;
    $('#as-of').textContent='—';$('#count').textContent='—';$('#universe').textContent='—';
    $('#status').className='notice error';
    $('#status').replaceChildren(node('strong','','無法提供有效的選股結果'),node('p','',String(error.message)),node('p','','未使用模擬行情或舊候選冒充本日資料。請檢查 GitHub Actions 執行紀錄與官方資料來源。'));
    $('#cards').replaceChildren();$('#empty').hidden=false;
    $('#empty-message').textContent='資料更新尚未成功，請待來源恢復並重新執行更新。';
  }
}
document.querySelectorAll('[data-market]').forEach(button=>button.addEventListener('click',()=>{
  market=button.dataset.market;
  document.querySelectorAll('[data-market]').forEach(b=>{b.classList.toggle('active',b===button);b.setAttribute('aria-pressed',String(b===button));});render();
}));
$('#search').addEventListener('input',render);$('#sort').addEventListener('change',render);
load();
