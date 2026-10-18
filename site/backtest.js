/* Preliminary research reports use verified historical quotes, never example P&L. */
(()=>{
  const find=s=>document.querySelector(s);
  const make=(tag,cls,text)=>{const el=document.createElement(tag);if(cls)el.className=cls;if(text!==undefined)el.textContent=text;return el;};
  const num=n=>Number(n).toLocaleString('zh-TW',{maximumFractionDigits:2});
  const pct=(n,digits=2)=>n===null?'—':`${(n*100).toLocaleString('zh-TW',{maximumFractionDigits:digits})}%`;
  let report;
  function detail(model){
    const box=find('#backtest-detail');box.replaceChildren();
    box.append(make('h3','',`${model.name}｜進出場紀錄`),make('p','',`已平倉 ${model.closed_count} 筆、未平倉 ${model.open_count} 筆；勝率只計已平倉，期末報酬含未平倉估值。`));
    const warnings=make('ul','research-warnings');model.warnings.forEach(w=>warnings.append(make('li','',w)));box.append(warnings);
    if(model.closed_trades.length){
      const scroll=make('div','table-scroll'),table=make('table','trade-table');
      const head=make('tr');['股票','訊號型態','訊號日','進場日','模型進場價','出場日','模型出場價','持有交易日','含成本損益','出場原因'].forEach(label=>head.append(make('th','',label)));table.append(head);
      model.closed_trades.slice().reverse().forEach(t=>{
        const row=make('tr');[`${t.code} ${t.name}`,t.signal_variant||model.name,t.signal_date,t.entry_date,num(t.entry_price),t.exit_date,num(t.exit_price),String(t.holding_sessions),num(t.net_pnl),t.exit_reason].forEach(value=>row.append(make('td','',value)));table.append(row);
      });scroll.append(table);box.append(scroll,make('p','table-hint','可左右滑動交易明細；價格為含滑價與跳動單位的模型估算，非實際委託成交紀錄。'));
    }else box.append(make('p','','此策略在本次期間沒有已平倉交易，無法據此推論勝率。'));
    if(model.open_positions.length){
      const list=make('ul');model.open_positions.forEach(p=>list.append(make('li','',`${p.code} ${p.name}｜${p.entry_date} 進場，持有 ${p.holding_sessions} 個交易日，尚未平倉${p.pending_exit?'（待下一可成交日出場）':''}`)));box.append(make('h4','','期末仍持有'),list);
    }
  }
  async function loadReport(){
    try{
      const response=await fetch('backtest.json',{cache:'no-store'});if(!response.ok)throw Error(`HTTP ${response.status}`);
      report=await response.json();
      if(report.schema_version!==1||report.status!=='preliminary'||!Array.isArray(report.models)||!report.models.length)throw Error((report.errors||[]).join('；')||'回測資料尚未準備');
      const starts=new Set(),ends=new Set();
      for(const m of report.models){
        if(!m.metrics||!Array.isArray(m.closed_trades)||!Array.isArray(m.open_positions)||!Array.isArray(m.warnings))throw Error('回測結果格式不完整');
        for(const k of ['total_return','max_drawdown','initial_capital','final_equity'])if(!Number.isFinite(m.metrics[k]))throw Error('回測數值不合法');
        if(m.metrics.win_rate!==null&&(!Number.isFinite(m.metrics.win_rate)||m.metrics.win_rate<0||m.metrics.win_rate>1))throw Error('回測勝率不合法');
        starts.add(m.start);ends.add(m.end);
      }
      if(starts.size!==1||ends.size!==1)throw Error('各策略回測期間不一致');
      const first=report.models[0],e=report.execution_parameters;
      find('#backtest-status').className='notice warning';
      find('#backtest-status').textContent='初步回測：原始價格未還原權息，未納入股息與完整撮合限制，尚未完成跨年度及樣本外驗證。正負報酬都如實列出，不自動選定「最佳」策略。';
      find('#backtest-period').textContent=`官方資料自 ${first.data_start}；共同模擬區間 ${first.start}～${first.end}，${first.simulated_sessions} 個交易日（暖機 ${first.warmup_sessions} 日）。`;
      const cards=find('#backtest-models');cards.replaceChildren();
      report.models.forEach(m=>{
        const card=make('article',`research-card ${m.model_id===report.user_model?'personal':''}`);card.append(make('h3','',m.name),make('p','',m.description));
        const metrics=make('dl','research-metrics');
        [['期末估算報酬',pct(m.metrics.total_return)],['最大估算回撤',pct(m.metrics.max_drawdown)],['已平倉／未平倉',`${m.closed_count}／${m.open_count}`],['已平倉勝率',pct(m.metrics.win_rate)]].forEach(([label,value])=>{const item=make('div');item.append(make('dt','',label),make('dd','',value));metrics.append(item);});
        const button=make('button','','查看進出場');button.type='button';button.addEventListener('click',()=>{detail(m);find('#backtest-detail').scrollIntoView({behavior:'smooth',block:'start'});});
        card.append(metrics,button);cards.append(card);
      });
      find('#backtest-assumptions').textContent=`共同假設：研究本金 ${num(e.initial_capital)} 元、最多 ${e.max_positions} 檔、每筆固定本金／${e.max_positions}，${e.lot_size} 股為單位。買賣手續費各 ${pct(e.fee_rate,4)}（最低 ${num(e.minimum_fee)} 元）、賣出稅 ${pct(e.sell_tax_rate)}、單邊滑價 ${pct(e.slippage_rate)}。第 ${e.profit_min_sessions} 日收盤起檢查停利，預定第 ${e.max_hold_sessions} 日開盤時間出場；收盤停損可提早，成交受限可延後。`;
      detail(report.models.find(m=>m.model_id===report.user_model)||first);
    }catch(error){
      find('#backtest-status').className='notice error';find('#backtest-status').textContent=`無法提供本次回測：${error.message}。未以範例績效代替結果。`;
      find('#backtest-models').replaceChildren();find('#backtest-detail').replaceChildren();
    }
  }
  loadReport();
})();
