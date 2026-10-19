/* Only recorded results. Empty/blocked research is never replaced with sample curves. */
(()=>{
 const q=s=>document.querySelector(s),make=(tag,text,cls='')=>{const e=document.createElement(tag);e.textContent=text;e.className=cls;return e;};
 const pct=v=>v==null?'—':`${(v*100).toFixed(2)}%`,num=v=>v==null?'—':Number(v).toLocaleString('zh-TW',{maximumFractionDigits:2});
 function table(headers,rows){const box=document.createElement('div');box.className='table-scroll';const t=document.createElement('table');t.className='naked-table';const head=document.createElement('tr');headers.forEach(h=>head.append(make('th',h)));t.append(head);rows.forEach(values=>{const r=document.createElement('tr');values.forEach(v=>r.append(make('td',String(v))));t.append(r);});box.append(t);return box;}
 function curve(points,key,title){
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 600 200');svg.setAttribute('role','img');svg.setAttribute('aria-label',title);const label=document.createElementNS(ns,'title');label.textContent=title;svg.append(label);
  const values=points.map(p=>p[key]);if(!values.length||values.some(v=>!Number.isFinite(v)))throw Error('曲線資料不合法');
  const lo=Math.min(...values),hi=Math.max(...values),line=document.createElementNS(ns,'polyline');line.setAttribute('points',points.map((p,i)=>`${10+i/(points.length-1||1)*580},${185-(p[key]-lo)/(hi-lo||1)*170}`).join(' '));line.setAttribute('fill','none');line.setAttribute('stroke','#176559');line.setAttribute('stroke-width','2');svg.append(line);return svg;
 }
 async function loadRuns(){
  const box=q('#run-history');box.replaceChildren();
  try{const response=await fetch('research-history.json',{cache:'no-store'});if(!response.ok)throw Error(`HTTP ${response.status}`);const h=await response.json();
   if(h.schema_version!==1||h.model_id!=='F'||!Array.isArray(h.runs))throw Error('回測紀錄格式不完整');
   if(!h.runs.length){box.append(make('p','尚未執行本合併策略的回測。'));return;}
   const labels={blocked:'資料／驗證條件未通過',error:'執行失敗',completed:'本輪已結束，請看是否通過驗證'};
   const archive=make('a','完整回測歷史（資料分支）');archive.href='https://github.com/sy3dren-collab/taiwan-stock-screener/tree/research-data/runs';box.append(make('p',`共 ${h.total_runs} 次執行；下方依時間顯示最近20次，沒有依績效挑選。`),archive);
   for(const run of h.runs.slice(0,20)){
    if(run.model_id!=='F')throw Error('回測紀錄與目前策略不同');
    const annual=run.command==='annual-research';
    const entry=document.createElement('details');entry.className='run-entry';const summary=make('summary',`${new Date(run.generated_at).toLocaleString('zh-TW',{timeZone:'Asia/Taipei',hour12:false})}（台北）｜${annual?'一年回溯研究':run.command==='final-test'?'封存測試檢查':'五年時序研究'}｜${labels[run.status]||run.status}｜${run.completed_experiments} 次有效實驗`);entry.append(summary);
    if(!run.trials.length)entry.append(make('p','本輪未產出有效回測：勝率／淨報酬／回撤皆為 —，不是0%。'));
    else entry.append(table(['輪次／修改','勝率／平倉筆數',annual?'一年帳戶淨報酬':'平均驗證淨報酬',annual?'最大回撤':'最大單折回撤','PF／期望值','是否保留'],run.trials.map(t=>[`${t.iteration}／${t.changed_rules.join(', ')||'固定基準'}`,`${pct(t.win_rate)}／${num(t.closed_count)}`,pct(annual?t.annual_net_return:t.mean_validation_return),pct(t.max_fold_drawdown),`${num(t.profit_factor)}／${num(t.expectancy)}`,t.retained?'保留研究候選':'未保留'])));
    const issues=document.createElement('ul');run.issues.forEach(v=>issues.append(make('li',v)));run.trials.forEach(t=>issues.append(make('li',`${t.reason}；${t.error||t.rejection_reasons.join('；')||t.status}`)));entry.append(issues,make('p',`程式版本 ${run.version?.git_commit?.slice(0,12)||'未取得'}。平均跨折報酬不是連續帳戶年報酬，85%僅為長期研究目標。`));
    if(run.download_url&&/^runs\/[A-Za-z0-9_-]+\.json$/.test(run.download_url)){const link=make('a','下載本次完整回測報告');link.href=run.download_url;link.download='';entry.append(link);}
    box.append(entry);
   }
  }catch(error){box.replaceChildren(make('p',`回測紀錄無法讀取：${error.message}。未以範例結果代替。`));}
 }
 async function loadAnnual(){
  const status=q('#annual-status'),stats=q('#annual-metrics'),evidence=q('#annual-evidence'),charts=q('#annual-charts');
  try{
   const response=await fetch('annual-backtest.json',{cache:'no-store'});if(!response.ok)throw Error(`HTTP ${response.status}`);const r=await response.json();
   if(r.schema_version!==1||r.research_model_id!=='F'||r.classification!=='retrospective_diagnostic'||r.promotion_allowed!==false)throw Error('一年研究格式不完整');
   stats.replaceChildren();evidence.replaceChildren();charts.replaceChildren();status.className='notice warning';
   if(r.status!=='completed'){
    status.textContent=r.status==='error'?`一年回測失敗：${r.run_error||'請看完整報告'}`:'正在補齊一年行情與事件資料，尚無有效回測結果。';
    const list=document.createElement('ul');(r.data_quality?.issues||[]).forEach(x=>list.append(make('li',x)));evidence.append(list);return;
   }
   const s=r.strategy,m=s?.metrics;
   if(!m||!Array.isArray(s.closed_trades)||s.closed_trades.length!==m.closed_count||!Number.isFinite(m.net_return)||!Number.isFinite(m.max_drawdown)||!Array.isArray(s.equity_curve))throw Error('一年績效或交易明細不一致');
   status.textContent='一年回溯研究已完成；這一年曾用於研究，並非獨立樣本外。正式策略仍未啟用。';
   stats.append(make('p',`${s.start}～${s.end}，共 ${num(r.period.trading_sessions)} 個交易日；${r.entry_cutoff} 後停止新進場，保留持倉結束時間。`),table(['勝率','一年帳戶淨報酬','已平倉交易','最大回撤','獲利因子'],[[pct(m.win_rate),pct(m.net_return),num(m.closed_count),pct(m.max_drawdown),num(m.profit_factor)]]));
   if(!m.closed_count)stats.append(make('p','沒有已完成交易，勝率為 —；0%帳戶報酬不能證明策略有效。'));
   stats.append(make('p',`獲利 ${num(m.winners)} 筆、虧損 ${num(m.losers)} 筆；費稅與滑價 ${num(m.total_costs)} 元，平均持有 ${num(m.average_holding_sessions)} 個交易日。${m.sample_warning}`));
   const quality=r.data_quality,f=r.signal_funnel||{};
   evidence.append(make('p',`已核對 ${num(quality.source_proofs)} 份兩市場日報／休市回應，暖機 ${num(quality.warmup_sessions)} 個交易日。共檢查 ${num(f.quoted)} 個股票日，通過資料與流動性檢查 ${num(f.admitted)} 個，策略訊號 ${num(f.signals)} 個。`));
   const warnings=document.createElement('ul');(quality.limitations||[]).forEach(x=>warnings.append(make('li',x)));evidence.append(warnings,make('p',`未知參考價／事件排除 ${num(f.unresolved_reference_or_event||0)} 個股票日、未支援公司行動 ${num(f.unsupported_corporate_action||0)} 個、停牌／無成交 ${num(f.suspension_or_unquoted||0)} 個。依當時已知資料排除，沒有事後刪除虧損交易。`));
   const download=make('a','下載這次完整一年回測（含全部交易與資料指紋）');download.href='annual-backtest.json';download.download='';evidence.append(download);
   charts.append(make('h4','一年研究淨值（含成本）'),curve(s.equity_curve,'equity','一年回溯研究模型淨值'),make('h4','最大回撤走勢'),curve(m.drawdown_curve,'drawdown','一年回溯研究回撤'),table(['月份','淨報酬'],m.monthly.map(x=>[x.period,pct(x.net_return)])),table(['股票代號／名稱','訊號／進場日','出場日','淨損益','出場原因'],s.closed_trades.map(t=>[`${t.entry_code} ${t.name}`,`${t.signal_date}／${t.entry_date}`,t.exit_date,num(t.net_pnl),t.exit_reason])));
  }catch(error){status.className='notice error';status.textContent=`一年回測報告無法讀取：${error.message}。`;stats.replaceChildren();evidence.replaceChildren();charts.replaceChildren();}
 }
 async function load(){
  try{
   const response=await fetch('research.json',{cache:'no-store'});if(!response.ok)throw Error(`HTTP ${response.status}`);const r=await response.json();
   if(r.schema_version!==1||r.research_model_id!=='F'||!Array.isArray(r.candidates)||r.candidates.length!==1||r.candidates[0].model_id!=='F'||!Array.isArray(r.experiments)||!r.data_quality)throw Error('研究報告尚未切換為目前唯一合併策略');
   q('#naked-active').className='notice warning';q('#naked-active').textContent=r.message||'尚無通過驗證的策略';
   const quality=q('#naked-quality');quality.replaceChildren();
   const qualityResponse=await fetch('data-quality.json',{cache:'no-store'});if(!qualityResponse.ok)throw Error(`資料檢查 HTTP ${qualityResponse.status}`);const d=await qualityResponse.json();
   if(d.schema_version!==1||!Array.isArray(d.issues))throw Error('資料檢查報告格式不完整');
   quality.append(make('p',`資料目標 ${d.requested_start}～${d.requested_end}；已存 ${num(d.bars)} 筆原始行情，仍缺 ${num(d.missing_weekdays)} 個工作日日報／休市證據。`));
   const list=document.createElement('ul');(d.issues||[]).forEach(v=>list.append(make('li',v)));quality.append(list);
   if(d.backfill){const b=d.backfill;quality.append(make('p',`最近歷史回補：${num(b.completed_dates)} 個日期、${num(b.http_requests)} 次請求、${num(b.elapsed_seconds)} 秒；最後完成 ${b.last_completed||'尚無'}。${b.error?'來源失敗：'+b.error:b.reason==='resource_budget'?'本輪預算已用完，下一輪續接。':'本輪已結束。'}`,b.error?'notice error':''));}
   const paperResponse=await fetch('paper.json',{cache:'no-store'});if(!paperResponse.ok)throw Error(`前瞻觀察 HTTP ${paperResponse.status}`);const paper=await paperResponse.json();
   quality.append(make('p',`檢查時間 ${new Date(d.generated_at).toLocaleString('zh-TW',{timeZone:'Asia/Taipei',hour12:false})}（台北）；最終封存樣本外：${r.final_holdout?.reason||r.final_holdout?.status||'尚未執行'}。前瞻紙上觀察：${paper.status==='inactive'?'尚未啟用':paper.status}。`));
   const comparisons=q('#naked-comparisons');comparisons.replaceChildren();r.candidates.forEach(c=>{const card=document.createElement('article');card.className='naked-candidate';card.append(make('h4',`${c.model_id}｜${c.name}`),make('p',c.status==='blocked'?'資料檢查未通過，未執行有效回測':c.status==='walk_forward_candidate'?'通過開發驗證，仍須封存樣本外與審核':'未通過／尚未完成驗證'));
    if(c.metrics)card.append(make('p',`跨折平均驗證報酬 ${pct(c.metrics.mean_validation_return)}，已平倉 ${c.metrics.closed_count} 筆。這不是全年連續帳戶報酬。`));else card.append(make('p','淨報酬、勝率與回撤：—（沒有有效結果）'));comparisons.append(card);});
   const history=q('#optimization-history');history.replaceChildren();
   if(!r.experiments.length)history.append(make('p','尚未執行有效實驗：資料檢查未通過。未捏造優化成功紀錄。'));
   else history.append(table(['實驗編號','修改與原因','驗證平均報酬','結果／保留','程式版本'],r.experiments.map(e=>[e.experiment_id,`${e.changed_rules.join(', ')||'基準'}：${e.reason}`,pct(e.assessment?.mean_validation_return),`${e.status}／${e.retained?'保留研究候選':'未保留'}`,e.version.git_commit.slice(0,12)])));
   // The active panel must be backed by an executed, passed final report and a daily active registry.
   const finalResponse=await fetch('active-performance.json',{cache:'no-store'});const f=finalResponse.ok?await finalResponse.json():{};
   const dailyResponse=await fetch('results.json',{cache:'no-store'});const day=dailyResponse.ok?await dailyResponse.json():{};
   const perf=q('#naked-performance'),charts=q('#naked-charts');perf.replaceChildren();charts.replaceChildren();
   const valid=f.status==='completed'&&f.executed&&f.result?.assessment?.passed&&day.mode==='active'&&day.strategy_version===f.result.frozen_sha256;
   if(!valid){perf.append(make('p','唯一正式策略：未啟用。一年勝率／淨報酬／交易數／回撤／獲利因子：—。'));charts.append(make('p','尚無通過驗證並啟用的策略；不顯示範例淨值或回撤曲線。'));return;}
   const s=f.result.strategy,m=s.metrics;
   if(!Number.isFinite(m.net_return)||!Number.isFinite(m.max_drawdown))throw Error('最終績效數值不合法');
   q('#naked-active').textContent=`正式唯一策略 ${s.model_id}｜凍結版本 ${day.strategy_version.slice(0,12)}，歷史結果不保證未來。`;
   perf.append(table(['一年勝率','一年淨報酬','交易數','最大回撤','獲利因子'],[[pct(m.win_rate),pct(m.net_return),m.closed_count,pct(m.max_drawdown),num(m.profit_factor)]]),make('p',`封存測試期間 ${s.start}～${s.end}。前瞻觀察績效另存，不與此歷史回測混用。`));
   charts.append(make('h4','累積淨值'),curve(s.equity_curve,'equity','封存期模型淨值曲線'),make('h4','回撤'),curve(m.drawdown_curve,'drawdown','封存期模型回撤曲線'),table(['月份','淨報酬'],m.monthly.map(x=>[x.period,pct(x.net_return)])),table(['股票','進場','出場','淨損益','原因'],s.closed_trades.map(t=>[`${t.code} ${t.name}`,t.entry_date,t.exit_date,num(t.net_pnl),t.exit_reason])));
   if(paper.status==='paper_model'&&paper.version===day.strategy_version){const pm=paper.report.metrics;charts.append(make('h4','前瞻模型觀察（與歷史回測分開）'),make('p',`${paper.forward_since} 起，淨報酬 ${pct(pm.net_return)}，已平倉 ${pm.closed_count} 筆。非真實委託成交。`),curve(paper.report.equity_curve,'equity','前瞻模型淨值'));}
  }catch(error){q('#naked-active').className='notice error';q('#naked-active').textContent=`研究資料無法讀取：${error.message}。未提供範例績效。`;for(const id of ['#naked-comparisons','#optimization-history','#naked-performance','#naked-charts','#naked-quality'])q(id).replaceChildren();}
 }
 const archive=document.querySelector('#legacy-watchlist');let loaded=false;
 if(archive)archive.addEventListener('toggle',async()=>{
  if(!archive.open||loaded)return;loaded=true;
  try{const response=await fetch('legacy-results.json',{cache:'no-store'});if(!response.ok)throw Error(`HTTP ${response.status}`);const snapshot=validateResult(await response.json());
   if(snapshot.status!=='ok')throw Error('封存快照不可用');snapshot.candidates.forEach((s,i)=>q('#legacy-cards').append(card(s,i+1)));
  }catch(error){q('#legacy-cards').replaceChildren(make('p',`封存資料無法讀取：${error.message}`));}
 });
 load();loadRuns();loadAnnual();
})();
