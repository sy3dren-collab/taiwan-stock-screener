/* Fixed research candidates; neither simulated fills nor fitted returns are live trades. */
(()=>{
  const find=s=>document.querySelector(s);
  const make=(tag,cls,text)=>{const el=document.createElement(tag);if(cls)el.className=cls;if(text!==undefined)el.textContent=text;return el;};
  const num=n=>n===null?'—':Number(n).toLocaleString('zh-TW',{maximumFractionDigits:2});
  const pct=(n,digits=2)=>n===null?'—':`${(n*100).toLocaleString('zh-TW',{maximumFractionDigits:digits})}%`;
  let report;
  function detail(model){
    const box=find('#backtest-detail');box.replaceChildren();
    box.append(make('h3','',`${model.name}｜進出場紀錄`),make('p','',`已平倉 ${model.closed_count} 筆、未平倉 ${model.open_count} 筆；勝率只計已平倉，期末報酬含未平倉估值。`));
    if(model.version==='candidate')box.append(make('p','notice warning','這是固定改良候選的研究紀錄，尚未取代今日選股策略。'));
    const warnings=make('ul','research-warnings');model.warnings.forEach(w=>warnings.append(make('li','',w)));box.append(warnings);
    if(model.diagnostics){
      const d=model.diagnostics,m=model.metrics;
      box.append(make('h4','','交易診斷'),make('p','',`已平倉手續費與稅 ${num(m.closed_fees_tax)} 元（另含模型滑價）；平均獲利 ${num(m.average_winner)} 元、平均虧損 ${num(m.average_loser)} 元，最長連虧 ${d.longest_losing_streak} 筆。平均資金曝險 ${pct(d.mean_exposure)}；持有現金較多可減少虧損，並不代表訊號本身更好。`));
      const reasons=make('ul');Object.entries(d.exit_reasons).forEach(([reason,v])=>reasons.append(make('li','',`${reason}：${v.count} 筆，淨損益 ${num(v.net_pnl)} 元`)));box.append(reasons);
    }
    if(model.closed_trades.length){
      const scroll=make('div','table-scroll'),table=make('table','trade-table');
      const head=make('tr');['股票','訊號型態','訊號日','進場日','模型進場價','出場日','模型出場價','持有交易日','含成本損益','出場原因'].forEach(label=>head.append(make('th','',label)));table.append(head);
      model.closed_trades.slice().reverse().forEach(t=>{
        const row=make('tr');[`${t.code} ${t.name}`,t.signal_variant||model.name,t.signal_date,t.entry_date,num(t.entry_price),t.exit_date,num(t.exit_price),String(t.holding_sessions),num(t.net_pnl),t.exit_reason].forEach(value=>row.append(make('td','',value)));table.append(row);
      });scroll.append(table);box.append(scroll,make('p','table-hint','可左右滑動交易明細；價格為含滑價與跳動單位的模型估算，非實際委託成交紀錄。'));
    }else box.append(make('p','','此版本在本次期間沒有已平倉交易，無法據此推論勝率。'));
    if(model.open_positions.length){
      const list=make('ul');model.open_positions.forEach(p=>list.append(make('li','',`${p.code} ${p.name}｜${p.entry_date} 進場，持有 ${p.holding_sessions} 個交易日，尚未平倉${p.pending_exit?'（待下一可成交日出場）':''}`)));box.append(make('h4','','期末仍持有'),list);
    }
  }
  function buttonFor(model,label){
    const button=make('button','',label);button.type='button';button.addEventListener('click',()=>{detail(model);find('#backtest-detail').scrollIntoView({behavior:'smooth',block:'start'});});return button;
  }
  function experiment(base){
    const exp=base.experiment,c=exp.candidate,box=make('div','experiment');
    box.append(make('h4','','固定改良候選 v1'),make('p','',`全年估算報酬 ${pct(c.metrics.total_return)}，最大回撤 ${pct(c.metrics.max_drawdown)}，已平倉 ${c.closed_count} 筆。`),make('p','assessment',exp.assessment));
    const scroll=make('div','table-scroll'),table=make('table','comparison-table');
    const head=make('tr');['期間','原版報酬','改良報酬','回撤：原／改','平倉：原／改'].forEach(t=>head.append(make('th','',t)));table.append(head);
    [['全年',{baseline:base,candidate:c}],['前八個月',exp.development],['後四個月',exp.validation]].forEach(([label,w])=>{
      const row=make('tr');[`${label}\n${w.baseline.start}～${w.baseline.end}`,pct(w.baseline.metrics.total_return),pct(w.candidate.metrics.total_return),`${pct(w.baseline.metrics.max_drawdown)}／${pct(w.candidate.metrics.max_drawdown)}`,`${w.baseline.closed_count}／${w.candidate.closed_count}`].forEach(v=>row.append(make('td','',v)));table.append(row);
    });scroll.append(table);box.append(scroll,make('p','table-hint','左右滑動比較。兩個分段各自從現金開始，報酬不可直接相加；全年則連續模擬。'));
    const details=make('details'),summary=make('summary','','設計弱點、改進假說與診斷');details.append(summary);
    const list=make('ul');exp.weaknesses.forEach(w=>list.append(make('li','',w)));details.append(list,make('p','',exp.changes));
    if(base.diagnostics)details.append(make('p','',`原版平均資金曝險 ${pct(base.diagnostics.mean_exposure)}，改良版 ${pct(c.diagnostics.mean_exposure)}；改善也可能來自減少持倉，不能只看總報酬。`));
    box.append(details,buttonFor(c,'查看改良版進出場'));return box;
  }
  function validateModel(m){
    if(!m.metrics||!Array.isArray(m.closed_trades)||!Array.isArray(m.open_positions)||!Array.isArray(m.warnings))throw Error('回測結果格式不完整');
    for(const k of ['total_return','max_drawdown','initial_capital','final_equity'])if(!Number.isFinite(m.metrics[k]))throw Error('回測數值不合法');
    if(m.metrics.win_rate!==null&&(!Number.isFinite(m.metrics.win_rate)||m.metrics.win_rate<0||m.metrics.win_rate>1))throw Error('回測勝率不合法');
  }
  async function loadReport(){
    try{
      const response=await fetch('backtest.json',{cache:'no-store'});if(!response.ok)throw Error(`HTTP ${response.status}`);
      report=await response.json();
      if(report.schema_version!==1||report.status!=='preliminary'||!Array.isArray(report.models)||!report.models.length)throw Error((report.errors||[]).join('；')||'回測資料尚未準備');
      const starts=new Set(),ends=new Set();
      for(const m of report.models){
        validateModel(m);starts.add(m.start);ends.add(m.end);
        if(m.experiment){
          validateModel(m.experiment.candidate);
          if(m.experiment.candidate.start!==m.start||m.experiment.candidate.end!==m.end)throw Error('原版與改良版期間不一致');
          for(const window of [m.experiment.development,m.experiment.validation]){
            if(window.baseline.start!==window.candidate.start||window.baseline.end!==window.candidate.end)throw Error('分段比較期間不一致');
            for(const version of ['baseline','candidate'])for(const key of ['total_return','max_drawdown'])if(!Number.isFinite(window[version].metrics[key]))throw Error('分段回測數值不合法');
          }
        }
      }
      if(starts.size!==1||ends.size!==1)throw Error('各策略回測期間不一致');
      const first=report.models[0],e=report.execution_parameters;
      find('#backtest-status').className='notice warning';
      find('#backtest-status').textContent='初步回測：原始價格未還原權息，未納入股息與完整撮合限制。每個原策略只測一個固定改良候選，保留失敗結果，不自動取代正式策略。';
      find('#backtest-period').textContent=`官方資料自 ${first.data_start}；共同模擬區間 ${first.start}～${first.end}，${first.simulated_sessions} 個交易日（暖機 ${first.warmup_sessions} 日）。`;
      const protocol=find('#research-protocol');if(protocol){protocol.replaceChildren();if(report.research_protocol){const p=report.research_protocol;protocol.append(make('p','',`比較方式：${p.development}；${p.validation}。每策略只測 ${p.candidate_count_per_model} 個固定改良版，不搜尋參數。`),make('p','notice warning',p.leakage_notice));p.limitations.forEach(t=>protocol.append(make('p','',t)));}}
      const cards=find('#backtest-models');cards.replaceChildren();
      report.models.forEach(m=>{
        const card=make('article',`research-card ${m.model_id===report.user_model?'personal':''}`);card.append(make('h3','',m.name),make('p','',m.description));
        const metrics=make('dl','research-metrics');
        [['原版期末估算報酬',pct(m.metrics.total_return)],['原版最大估算回撤',pct(m.metrics.max_drawdown)],['已平倉／未平倉',`${m.closed_count}／${m.open_count}`],['已平倉勝率',pct(m.metrics.win_rate)]].forEach(([label,value])=>{const item=make('div');item.append(make('dt','',label),make('dd','',value));metrics.append(item);});
        card.append(metrics,buttonFor(m,'查看進出場'));if(m.experiment)card.append(experiment(m));cards.append(card);
      });
      const r=report.refinement_parameters;
      find('#backtest-assumptions').textContent=`共同假設：研究本金 ${num(e.initial_capital)} 元、最多 ${e.max_positions} 檔、每筆上限本金／${e.max_positions}，${e.lot_size} 股為單位。買賣手續費各 ${pct(e.fee_rate,4)}（最低 ${num(e.minimum_fee)} 元）、賣出稅 ${pct(e.sell_tax_rate)}、單邊滑價 ${pct(e.slippage_rate)}。第 ${e.profit_min_sessions} 日收盤起檢查停利，預定第 ${e.max_hold_sessions} 日開盤時間出場；收盤停損可提早，成交受限可延後。${r?`改良版另限制每筆初始停損風險金額不超過本金 ${pct(r.risk_budget_fraction)}（跳空仍可超損）；收盤達 ${r.breakeven_trigger_r}R 後停損提高至進場價，第 ${r.failure_sessions} 日起未達 ${r.failure_min_r}R 則次日開盤退場。R 為模型進場價減初始停損；保本價仍可能扣費後虧損。`:''}`;
      detail(report.models.find(m=>m.model_id===report.user_model)||first);
    }catch(error){
      find('#backtest-status').className='notice error';find('#backtest-status').textContent=`無法提供本次回測：${error.message}。未以範例績效代替結果。`;
      for(const selector of ['#backtest-models','#backtest-detail','#backtest-period','#backtest-assumptions','#research-protocol'])if(find(selector))find(selector).replaceChildren();
    }
  }
  loadReport();
})();
