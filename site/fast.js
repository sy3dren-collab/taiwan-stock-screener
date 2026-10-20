fetch('fast-backtest.json', {cache: 'no-store'}).then(r => {
  if (!r.ok) throw new Error('尚無短期回測報告');
  return r.json();
}).then(data => {
  const root = document.getElementById('fast-results');
  const add = text => { const p = document.createElement('p'); p.textContent = text; root.append(p); };
  root.textContent = '';
  add(`最近報告：${data.generated_at}｜總耗時 ${data.elapsed_seconds} 秒`);
  const names = {'baseline':'舊版基準','causal-recovery-v2':'事件順序修正版','flexible-retest-v2':'修正版＋回測容許區間'};
  for (const r of data.short_runs) {
    const s = r.strategy, trades = s?.closed_trades || [];
    const wins = trades.filter(t => t.net_pnl > 0).length;
    add(`${names[r.candidate] || r.candidate}｜${r.period?.start || ''}～${r.period?.end || ''}｜${trades.length} 筆交易｜淨報酬 ${s ? (s.metrics.net_return * 100).toFixed(2) + '%' : '無有效結果'}｜勝率 ${trades.length ? (wins / trades.length * 100).toFixed(1) + '%' : '無交易，無法計算'}｜${r.elapsed_seconds || 0} 秒`);
    if (r.run_error) add(`此版本回測失敗：${r.run_error}；無有效績效。`);
    if (s?.unsettled_stock_dividends) add(`含 ${s.unsettled_stock_dividends} 筆未撥入股票股利：報酬含應收股票估值，不能視為全數已實現；勝率僅依已結束交易現金損益，尚不能通過長期回測門檻。`);
  }
  add(data.long_gate);
  if (data.long_run) {
    const r = data.long_run;
    add(`一年確認：${r.candidate}｜${r.status}｜淨報酬 ${r.strategy ? (r.strategy.metrics.net_return * 100).toFixed(2) + '%' : '無有效結果'}`);
  }
  data.limitations.forEach(add);
}).catch(e => { document.getElementById('fast-results').textContent = e.message; });
