"""Three-month observation coverage audit; not a portfolio performance backtest."""
from bisect import bisect_right
from dataclasses import asdict
from datetime import datetime,timezone
import json
from pathlib import Path
import time

from screener.__main__ import write_json
from screener.data import Store,Bar
from screener.naked import NakedParameters
from screener.watchlist import provider


def main():
    began=time.monotonic();deadline=began+180
    cfg=json.loads(Path('annual_research.json').read_text())
    start=json.loads(Path('fast_research.json').read_text())['short_start']
    p=NakedParameters(**json.loads(Path('naked_k.json').read_text())['signal'])
    store=Store('.state/prices.sqlite3')
    try:
        sessions=[r[0] for r in store.db.execute('SELECT DISTINCT date FROM bars WHERE date BETWEEN ? AND ? ORDER BY date',(cfg['data_start'],cfg['end']))]
        days=[d for d in sessions if start<=d<=cfg['end']]
        first=sessions[max(0,sessions.index(days[0])-p.lookback)]
        histories={}
        for row in store.db.execute('SELECT * FROM bars WHERE date BETWEEN ? AND ? ORDER BY date,market,code',(first,cfg['end'])):
            b=Bar(*row);histories.setdefault((b.market,b.code),[]).append(b)
        index={k:[b.date for b in bs] for k,bs in histories.items()}
        signals=provider(store,p,sessions,False);daily=[]
        for day in days:
            if time.monotonic()>deadline:raise TimeoutError('觀察覆蓋檢查超過180秒，不能冒充完整三個月')
            known={}
            for k,bs in histories.items():
                n=bisect_right(index[k],day);known[k]=bs[max(0,n-p.lookback-1):n]
            view=signals(known,day)
            daily.append({'date':day,'eligible':signals.daily[-1].get('signals',0),
                          'selected':len(view['candidates']),
                          'confirmed':sum(s['entry_confirmed'] for s in view['candidates']),
                          'event_observations':sum(s['variant']=='事件後等待回測轉強' for s in view['candidates']),
                          'codes':[s['market']+':'+s['code'] for s in view['candidates']]})
            if len(daily)%20==0:print(f'watchlist {len(daily)}/{len(days)}',flush=True)
        result={'classification':'observation_coverage_not_performance_backtest','status':'completed',
                'generated_at':datetime.now(timezone.utc).isoformat(),'period':{'start':days[0],'end':days[-1]},
                'trading_sessions':len(days),'target_count':10,'minimum_daily_count':min(r['selected'] for r in daily),
                'average_daily_count':sum(r['selected'] for r in daily)/len(days),
                'days_with_ten':sum(r['selected']==10 for r in daily),'daily':daily,
                'parameters':json.loads(Path('watchlist.json').read_text()),
                'elapsed_seconds':round(time.monotonic()-began,3),'orders_enabled':False,
                'note':'只檢查每日研究觀察名單數量，不將觀察股票當作進場、不計算或宣稱策略收益。進場規則與三個月交易回測分開。'}
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        write_json(Path('site/watchlist-audits')/(stamp+'.json'),result)
        write_json(Path('site/watchlist-audit.json'),result)
        print(json.dumps({k:v for k,v in result.items() if k not in ('daily','parameters')},ensure_ascii=False),flush=True)
    finally:store.close()


if __name__=='__main__':main()
