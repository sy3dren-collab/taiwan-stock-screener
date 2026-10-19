'use strict';
const $ = (selector) => document.querySelector(selector);
let data = null;
let market = 'all';
let strategyId = 'trend_pullback';
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
  const caption = node('p','chart-caption');caption.append(node('span','',stock.chart_price_basis||'最近 60 個交易日 · 下方為成交量'),node('span','','┄ 支撐'));
  const levels = node('dl','levels');
  [['支撐價格',stock.support],['參考停損',stock.stop],['參考目標',stock.target],['風險報酬比',`${format(stock.reward_risk)} 倍`]].forEach(([label,value])=>{
    const item=node('div'); item.append(node('dt','',label),node('dd','',typeof value==='number'?format(value,3):value));levels.append(item);
  });
  const reasons = node('ul','reasons');stock.reasons.forEach(reason=>reasons.append(node('li','',reason)));
  const foot = node('div','stock-foot');foot.append(node('span','',`行情 ${stock.date} · 成交量單位：股`),node('span','',`排序分數 ${format(stock.score,1)}`));
  el.append(top);
  if(stock.variant)el.append(node('p','pattern-label',stock.variant));
  el.append(graph,caption,levels);
  if (stock.entry_plan) {
    const plan=stock.entry_plan;
    const box=node('div','entry-plan');
    box.append(node('h4','','波段進場計畫'),node('p','',`收盤訊號確認後，觀察下一交易日開盤；參考開盤上限 ${format(plan.maximum_open,3)} 元。超過上限或滑價後風報比不足時跳過。`),node('p','',`目標持有 ${plan.profit_min_sessions}～${plan.max_hold_sessions} 個交易日；${plan.stop_rule}。${plan.time_rule}。`));
    el.append(box);
  }
  if(stock.strategy_version)el.append(node('p','',`凍結版本 ${stock.strategy_version.slice(0,12)}｜進場至停損風險 ${(stock.risk_fraction*100).toFixed(2)}%｜${stock.signal_status}`));
  el.append(node('p','reason-title','入選依據'),reasons,foot);
  return el;
}
function render() {
  $('#cards').replaceChildren();
  if (!data || data.status !== 'ok') return;
  if(data.mode==='research'){
    $('#count').textContent='0';$('#universe').textContent=format(data.universe_count,0);
    $('#status').className='notice warning';$('#status').replaceChildren(node('strong','',data.message||'尚無通過驗證的策略'));
    (data.warnings||[]).forEach(w=>$('#status').append(node('p','',w)));
    $('#empty').hidden=false;$('#empty-message').textContent='尚無通過驗證的策略。今日不提供正式選股名單，也不以封存模型補入。';
    $('.strategy-picker').hidden=true;return;
  }
  $('.strategy-picker').hidden=Object.keys(data.strategies||{}).length<=1;
  const query = $('#search').value.trim().toLowerCase();
  const sort = $('#sort').value;
  const view=data.strategies?.[strategyId] || data;
  $('#count').textContent=view.candidates.length;
  $('#universe').textContent=format(view.universe_count,0);
  const warnings=[...(data.source_warnings || data.warnings || [])];
  if(view.shortfall && data.mode==='active') warnings.push('今日無符合策略條件的股票，未放寬標準。');
  else if(view.shortfall && data.strategies) warnings.push(`此策略僅 ${view.candidates.length} 檔符合全部條件，少於目標 ${data.parameters.target_count} 檔；未放寬條件湊數。`);
  if(data.strategies && view.sufficient_history_count<view.universe_count) warnings.push(`${view.universe_count-view.sufficient_history_count} 檔歷史不足 ${view.required_bars} 根，未參與此策略判斷。`);
  if((Date.now()-new Date(`${data.as_of}T00:00:00+08:00`).getTime())/86400000>4) warnings.push('行情距今超過 4 天，請核對休市公告與更新排程。');
  $('#status').className=`notice ${warnings.length?'warning':''}`;
  $('#status').replaceChildren(node('p','',`${view.name || '選股策略'} · 資料截至 ${data.as_of} 收盤。${view.qualified_count} 檔符合，顯示 ${view.candidates.length} 檔。`));
  warnings.forEach(message=>$('#status').append(node('p','',message)));
  $('#strategy-description').textContent=view.description || '';
  const stocks = view.candidates.filter(stock=>(market==='all'||stock.market===market)&&`${stock.code} ${stock.name}`.toLowerCase().includes(query));
  stocks.sort((a,b)=>sort==='code'?a.code.localeCompare(b.code):b[sort]-a[sort]||a.code.localeCompare(b.code));
  stocks.forEach((stock,i)=>$('#cards').append(card(stock,i+1)));
  $('#empty').hidden=stocks.length>0;
  $('#empty-message').textContent=view.candidates.length===0?'此策略本次沒有股票符合全部條件。沒有合格標的時，不放寬條件湊數。':'此市場或搜尋條件沒有候選股票，請調整篩選。';
}
const labels = {
  fast_ma:'短期均線（交易日）',slow_ma:'長期均線（交易日）',slope_days:'均線升幅觀察日數',pivot_radius:'確認轉折左右根數',structure_days:'波段結構觀察日數',pullback_days:'回檔量縮觀察日數',volume_baseline_days:'量能基準日數',volume_ratio_max:'回檔均量／基準均量上限',support_distance_max:'支撐距離上限',minimum_pullback:'最小回檔深度',minimum_slope:'短均線最小升幅（須大於）',atr_days:'ATR 計算日數',stop_atr_buffer:'停損 ATR 緩衝倍數',max_risk_fraction:'停損距離／收盤上限',min_reward_risk:'最低風險報酬比',min_average_volume:'最低平均成交股數',max_daily_gap:'單日收盤變動絕對值上限',target_count:'最低目標檔數',max_candidates:'最多候選檔數'
};
function validateResult(result) {
  if (!result || result.schema_version !== 1 || !['ok','error'].includes(result.status) || !Array.isArray(result.candidates)) throw new Error('結果格式不正確');
  if (result.status==='ok') {
    if (!result.as_of || !result.parameters || !Number.isFinite(result.universe_count)) throw new Error('結果缺少行情日期或策略參數');
    const candidates=result.strategies?Object.values(result.strategies).flatMap(view=>{if(!view || !Array.isArray(view.candidates) || !Number.isFinite(view.universe_count))throw new Error('策略資料不完整');return view.candidates;}):result.candidates;
    for (const s of candidates) {
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
    strategyId=data.active_model || 'trend_pullback';
    const selector=$('#strategy-select');selector.replaceChildren();
    const choices=data.strategies || {trend_pullback:{name:'原策略：趨勢回檔再轉強'}};
    Object.entries(choices).forEach(([key,value])=>{const option=node('option','',value.name);option.value=key;selector.append(option);});
    selector.value=strategyId;
    $('#show-user-strategy').disabled=!data.strategies?.user_range_reclaim;
    if(data.model_parameters){
      const m=data.model_parameters;
      const list=node('ul');
      [`整理 ${m.range_days} 日，區間振幅 ≤ ${format(m.range_width_max*100)}%，首尾 ${m.range_edge_days} 日均價漂移 ≤ ${format(m.range_drift_max*100)}%`,
       `假跌破：最近 ${m.recovery_days} 日跌破下緣 ${format(m.minimum_break_fraction*100)}%～${format(m.maximum_break_fraction*100)}%，收盤站回下緣以上 ${format(m.reclaim_buffer*100)}%`,
       `收復／頸線突破當日成交量 ≥ 前 ${data.parameters.volume_baseline_days} 日均量 ${format(m.event_volume_multiple)} 倍（必要條件）`,
       `近似頭肩底：轉折左右各 ${m.pattern_pivot_radius} 根確認；頭部至少低於兩肩 ${format(m.head_depth_min*100)}%，兩肩價差 ≤ ${format(m.shoulder_tolerance*100)}%`,
       `兩段肩頭間距各 ${m.shoulder_min_spacing}～${m.shoulder_max_spacing} 根，時間比例 ≤ ${format(m.shoulder_time_ratio_max)} 倍`,
       `仍須通過流動性、最大風險與最低風險報酬比；不要求其他策略的均線多頭條件`].forEach(t=>list.append(node('li','',t)));
      $('#personal-parameters').replaceChildren(list);
    }
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
$('#strategy-select').addEventListener('change',event=>{strategyId=event.target.value;render();});
$('#show-user-strategy').addEventListener('click',()=>{strategyId='user_range_reclaim';$('#strategy-select').value=strategyId;render();$('#results-title').scrollIntoView({behavior:'smooth',block:'start'});});
$('#search').addEventListener('input',render);$('#sort').addEventListener('change',render);
load();
