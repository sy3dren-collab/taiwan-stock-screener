"""Bounded, explicitly retrospective one-year diagnostics; never a promotion path."""
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from datetime import date, datetime, timedelta, timezone
import argparse
import json
from pathlib import Path
import time
from dataclasses import asdict,replace
import hashlib
import math
from collections import Counter
from threading import Lock

from .data import DataError, OfficialClient, Store, URLS
from .distributions import fetch_distributions,reconcile_distributions,event_tables
from .quality import actions

VARIANTS={
    'baseline':{'name':'固定基準：整理寬度25%','changes':{},'reason':'原始合併策略固定基準，不因零訊號刪除結果。'},
    'wider-range':{'name':'單條件研究：整理寬度30%','changes':{'range_width':.30},
                   'reason':'基準在131078個資料准入股票日沒有訊號；18612個轉強K線中15657個先被整理寬度／漂移門檻排除。只測區間寬度25%→30%，漂移、量能、結構及風險全部不變；同一年已知資料，非獨立驗證。'},
}


class RequestGate:
    """A shared attempt budget and at most one request/second to each host."""
    def __init__(self,maximum,deadline):
        self.maximum=maximum;self.deadline=deadline;self.count=0;self.lock=Lock()
        self.host_locks={m:Lock() for m in URLS};self.last={m:0 for m in URLS}

    def __call__(self,market):
        with self.host_locks[market]:
            time.sleep(max(0,1-(time.monotonic()-self.last[market])))
            with self.lock:
                if self.count>=self.maximum:raise DataError('官方請求預算已用完')
                if time.monotonic()>=self.deadline:raise DataError('官方時間預算已用完')
                self.count+=1
            self.last[market]=time.monotonic()


def backfill_year(store, cfg, client_factory=OfficialClient):
    """At most three dates in flight, >=1 second between requests to each host.

    SQLite writes remain on the calling thread. Both markets commit atomically.
    Each attempt (including retries) consumes the bounded request budget.
    """
    maximum=int(cfg['max_backfill_dates']);requests=int(cfg['max_requests'])
    seconds=float(cfg['backfill_seconds'])
    if not 1<=maximum<=250 or not 2<=requests<=500 or not 0<seconds<=1800:
        raise ValueError('年度回補每輪最多250日期／500請求／1800秒')
    began=time.monotonic();deadline=began+seconds
    gate=RequestGate(requests,deadline);clients=[]
    day=date.fromisoformat(cfg['data_start']);end=date.fromisoformat(cfg['end'])
    needed=[]
    while day<=end:
        if day.weekday()<5:
            proof=store.db.execute('SELECT COUNT(*) FROM source_batches WHERE date=?',(day.isoformat(),)).fetchone()[0]
            unknown=store.db.execute('SELECT COUNT(*) FROM bars WHERE date=? AND turnover IS NULL',(day.isoformat(),)).fetchone()[0]
            if proof!=2 or unknown:needed.append(day)
        day+=timedelta(days=1)
    queue=iter(needed[:maximum]);done=0;last=None;error=None;partial=False
    batches={};pending={}
    with ThreadPoolExecutor(max_workers=6) as pool:
        while True:
            while not error and not partial and len(batches)<3:
                if gate.count+6>requests or time.monotonic()>deadline-2:partial=True;break
                candidate=next(queue,None)
                if candidate is None:break
                batches[candidate]={'reports':{},'proof':{},'finished':0,'failed':False}
                for market in URLS:
                    client=client_factory(delay=1,retries=3,timeout=25,request_budget=3,deadline=deadline,request_gate=gate)
                    clients.append(client);pending[pool.submit(client.daily,market,candidate)]=(candidate,market,client)
            if not pending:break
            completed,_=wait(pending,return_when=FIRST_COMPLETED)
            for future in completed:
                candidate,market,client=pending.pop(future);batch=batches[candidate];batch['finished']+=1
                try:
                    batch['reports'][market]=future.result();batch['proof'][market]=dict(client.provenance[market])
                except Exception as exc:
                    batch['failed']=True
                    if '預算已用完' in str(exc):partial=True
                    else:error=str(exc)
                if batch['finished']==2:
                    if not batch['failed']:
                        store.save_day(candidate,batch['reports'],batch['proof'])
                        done+=1;last=max(last or candidate.isoformat(),candidate.isoformat())
                        print(f'official {candidate} TWSE={len(batch["reports"]["TWSE"])} TPEX={len(batch["reports"]["TPEX"])}',flush=True)
                    del batches[candidate]
    complete=not error and not partial and done==len(needed)
    result={'status':'error' if error else 'complete' if complete else 'partial',
            'completed_dates':done,'last_completed':last,'http_requests':sum(c.request_count for c in clients),
            'elapsed_seconds':round(time.monotonic()-began,2),'error':error,
            'reason':'source_error' if error else 'complete' if complete else 'resource_budget',
            'requested_start':cfg['data_start'],'requested_end':cfg['end']}
    store.db.execute('CREATE TABLE IF NOT EXISTS ingestion_runs(created_at TEXT,payload TEXT)')
    with store.db:store.db.execute('INSERT INTO ingestion_runs VALUES (?,?)',(datetime.now(timezone.utc).isoformat(),json.dumps(result,ensure_ascii=False)))
    return result


def audit_year(store,cfg):
    """Full-market daily evidence is mandatory, lifecycle coverage stays separate.

    Unlike the five-year promotion audit, diagnostic admission checks one year's
    actual source coverage and reports security-level barriers explicitly.
    It cannot enable final testing, freezing, promotion or recommendations.
    """
    event_tables(store);start,end=cfg['data_start'],cfg['end'];issues=[]
    checked={r[0] for r in store.db.execute('SELECT date FROM sessions WHERE date BETWEEN ? AND ?',(start,end))}
    day=date.fromisoformat(start);missing=[]
    while day<=date.fromisoformat(end):
        if day.weekday()<5 and day.isoformat() not in checked:missing.append(day.isoformat())
        day+=timedelta(days=1)
    if missing:issues.append(f'缺 {len(missing)} 個工作日兩市場官方日報／休市證據')
    proofs=store.db.execute('SELECT COUNT(*) FROM source_batches WHERE date BETWEEN ? AND ?',(start,end)).fetchone()[0]
    if proofs!=2*len(checked):issues.append('每個已檢查日期必須有兩市場官方來源證據')
    mismatch=store.db.execute('''SELECT COUNT(*) FROM sessions s WHERE s.date BETWEEN ? AND ? AND
      (s.twse_count!=(SELECT COUNT(*) FROM bars b WHERE b.date=s.date AND b.market='TWSE') OR
       s.tpex_count!=(SELECT COUNT(*) FROM bars b WHERE b.date=s.date AND b.market='TPEX'))''',(start,end)).fetchone()[0]
    if mismatch:issues.append(f'{mismatch} 個日期行情筆數不完整')
    bad=store.db.execute('SELECT COUNT(*) FROM bars WHERE date BETWEEN ? AND ? AND (turnover IS NULL OR turnover<0)',(start,end)).fetchone()[0]
    if bad:issues.append(f'{bad} 筆缺官方成交金額，禁止以收盤乘量補值')
    coverage={r[0] for r in store.db.execute('SELECT market FROM distribution_sources WHERE start<=? AND end>=? AND LENGTH(payload_sha256)=64',(start,end))}
    if coverage!=set(URLS):issues.append('缺兩市場完整查詢期間的除權息原始表')
    if store.db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':issues.append('SQLite 完整性失敗')
    digest=hashlib.sha256();evidence=hashlib.sha256()
    for row in store.db.execute('SELECT * FROM bars WHERE date BETWEEN ? AND ? ORDER BY date,market,code',(start,end)):
        digest.update(json.dumps(row,separators=(',',':'),ensure_ascii=False).encode()+b'\n')
    for row in store.db.execute('SELECT * FROM source_batches WHERE date BETWEEN ? AND ? ORDER BY date,market',(start,end)):
        evidence.update(json.dumps(row,separators=(',',':')).encode()+b'\n')
    for row in store.db.execute('SELECT payload,source_sha256 FROM distribution_rows WHERE date BETWEEN ? AND ? ORDER BY date,market,code',(start,end)):
        # Only parsed historical event inputs influence strategy/results.
        # Current financial-statement fields in the raw official table must
        # neither influence signals nor invalidate an unchanged comparison.
        digest.update(row[0].encode()+b'\n')
        evidence.update(json.dumps(row,separators=(',',':')).encode()+b'\n')
    for action in actions(store):
        if start<=action.effective_date<=end and action.announced_date<=end:
            digest.update(json.dumps(asdict(action),sort_keys=True,separators=(',',':')).encode()+b'\n')
    for row in store.db.execute('SELECT * FROM distribution_sources WHERE start<=? AND end>=? ORDER BY market,start,end',(start,end)):
        evidence.update(json.dumps(row,separators=(',',':')).encode()+b'\n')
    sessions=[r[0] for r in store.db.execute('SELECT DISTINCT date FROM bars WHERE date BETWEEN ? AND ? ORDER BY date',(cfg['start'],end))]
    warmup=store.db.execute('SELECT COUNT(DISTINCT date) FROM bars WHERE date>=? AND date<?',(start,cfg['start'])).fetchone()[0]
    from .naked import NakedParameters
    if warmup<NakedParameters().lookback:issues.append(f'暖機只有 {warmup} 交易日，不足100日')
    if not sessions or sessions[-1]!=end:issues.append('回測結束日缺行情，禁止縮短期間冒充全年')
    return {'status':'blocked' if issues else 'diagnostic_ready','issues':issues,'data_sha256':digest.hexdigest(),
            'fingerprint_version':2,'evidence_sha256':evidence.hexdigest(),
            'requested_start':start,'requested_end':end,'test_start':cfg['start'],
            'missing_weekdays':len(missing),'source_proofs':proofs,'warmup_sessions':warmup,
            'trading_sessions':len(sessions),'missing_turnover':bad,
            'missing_reference':store.db.execute('SELECT COUNT(*) FROM bars WHERE date BETWEEN ? AND ? AND reference IS NULL',(start,end)).fetchone()[0],
            'formal_research_ready':False,'promotion_allowed':False,
            'limitations':['最近一年已被研究使用，本結果為回溯研究，非獨立樣本外。',
                           '完整分割／減資／下市與身份變更母表未齊；未知事件中斷該股訊號暖機，持倉遇未知事件則整輪失敗。',
                           '歷史股票池採當日日報四位數股票規則，未以今天存續名單回篩；完整歷史證券類別母表仍未取得。']}


class GuardedSignals:
    """Past-only per-security admission; never exclude using future outcomes."""
    def __init__(self,p,events,sessions,barriers=(),evaluator=None):
        self.evaluator=evaluator
        self.p=p;self.events=events;self.history_limit=p.lookback+1
        self.sessions={day:i for i,day in enumerate(sessions)}
        self.by_day={};self.by_security={}
        for a in events:
            self.by_day.setdefault((a.market,a.code,a.effective_date),[]).append(a)
            self.by_security.setdefault((a.market,a.code),[]).append(a)
        self.counts=Counter();self.daily=[]
        self.barriers={(b['market'],b['code'],b['date']) for b in barriers}

    def __call__(self,known,day):
        from .naked import evaluate
        from .quality import adjusted_history
        selected=[];funnel=Counter()
        for key,bars in known.items():
            if not bars or bars[-1].date!=day:continue
            funnel['quoted']+=1
            if len(bars)<self.p.lookback+1:funnel['insufficient_history']+=1;continue
            window=bars[-self.p.lookback-1:]
            if any(b.turnover is None for b in window[-self.p.liquidity_days:]):funnel['missing_turnover']+=1;continue
            if window[-1].close<self.p.minimum_price or sum(b.turnover for b in window[-self.p.liquidity_days:])/self.p.liquidity_days<self.p.minimum_turnover:
                funnel['price_or_liquidity']+=1;continue
            invalid=None
            for previous,current in zip(window,window[1:]):
                if (*key,current.date) in self.barriers:invalid='unsupported_corporate_action';break
                matching=[a for a in self.by_day.get((*key,current.date),[]) if a.announced_date<=current.date]
                explicit=[a.reference_price for a in matching if a.reference_price is not None]
                expected=explicit[-1] if explicit else previous.close*math.prod(a.price_factor for a in matching)
                if current.reference is None or abs(current.reference-expected)>.005:
                    invalid='unresolved_reference_or_event';break
                if self.sessions[current.date]-self.sessions[previous.date]!=1 or current.volume<=0:
                    invalid='suspension_or_unquoted';break
            if invalid:funnel[invalid]+=1;continue
            funnel['admitted']+=1
            relevant=[a for a in self.by_security.get(key,[]) if a.effective_date<=day and a.announced_date<=day]
            result=(self.evaluator or evaluate)(adjusted_history(window[-self.p.lookback:],day,relevant),'F',self.p)
            if result:selected.append(result)
        selected.sort(key=lambda s:(-s['score'],s['market'],s['code']))
        funnel['signals']=len(selected);self.counts.update(funnel);self.daily.append({'date':day,**funnel})
        return {'candidates':selected[:10]}


def run_year(store,cfg,parameters=None,execution=None,seconds=None,variant='baseline',quality=None):
    from .naked import NakedParameters
    from .naked_backtest import Risk,simulate
    from .execution import Execution
    from .optimizer import code_version
    if variant not in VARIANTS:raise ValueError('未知的一年研究版本')
    now=datetime.now(timezone.utc).isoformat();version=code_version()
    quality=audit_year(store,cfg) if quality is None else quality
    result={'schema_version':1,'generated_at':now,'research_model_id':'F','status':'blocked',
            'classification':'retrospective_diagnostic','promotion_allowed':False,'active_strategy':None,
            'data_quality':quality,'version':version,'experiments':[],'variant':{'id':variant,**VARIANTS[variant]},
            'message':'一年回溯研究，不能作為正式晉級或獨立樣本外績效。'}
    if quality['status']!='diagnostic_ready':result['stop_reason']='annual_data_quality';return result
    p=parameters or NakedParameters(**json.loads(Path('naked_k.json').read_text())['signal'])
    baseline_parameters=asdict(p);p=replace(p,**VARIANTS[variant]['changes'])
    base=json.loads(Path('naked_k.json').read_text());risk=Risk(**base['risk'])
    e=execution or Execution(**json.loads(Path('execution.json').read_text()))
    duration=cfg['simulation_seconds'] if seconds is None else seconds
    if not 0<duration<=1800:raise ValueError('年度模擬預算最多1800秒')
    # The query bound prevents even loading future sessions. No current-survivor filter.
    histories={}
    from .data import Bar
    for row in store.db.execute('SELECT * FROM bars WHERE date BETWEEN ? AND ? ORDER BY date,market,code',(cfg['data_start'],cfg['end'])):
        b=Bar(*row);histories.setdefault((b.market,b.code),[]).append(b)
    sessions=sorted({b.date for bs in histories.values() for b in bs});days=[d for d in sessions if cfg['start']<=d<=cfg['end']]
    events=[a for a in actions(store) if a.effective_date<=cfg['end'] and a.announced_date<=cfg['end']]
    barriers=[json.loads(r[0]) for r in store.db.execute('SELECT payload FROM distribution_rows WHERE date BETWEEN ? AND ?',(cfg['data_start'],cfg['end'])) if not json.loads(r[0])['supported']]
    provider=GuardedSignals(p,events,sessions,barriers)
    if len(days)<=e.max_hold_sessions:raise DataError('年度回測交易日不足')
    cutoff=days[-e.max_hold_sessions-1]
    result.update(config=cfg,parameters=asdict(p),baseline_parameters=baseline_parameters,execution=asdict(e),risk=asdict(risk),entry_cutoff=cutoff,budget_seconds=duration,
                  period={'start':days[0],'end':days[-1],'trading_sessions':len(days)})
    began=time.monotonic()
    try:
        report=simulate(histories,p,e,risk,'F',cfg['start'],cfg['end'],events,time.monotonic()+duration,provider,cutoff,security_barriers=barriers)
        if report['open_positions']:raise DataError('期末仍有不可成交持倉，不能略去或假設已平倉')
        result.update(status='completed',stop_reason='complete',strategy=report)
    except Exception as exc:
        result.update(status='error',stop_reason='data_or_execution_error',run_error=str(exc))
    result.update(signal_funnel=dict(provider.counts),daily_admission=provider.daily,elapsed_seconds=round(time.monotonic()-began,3))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['backfill','events','research'])
    parser.add_argument('--config',default='annual_research.json')
    parser.add_argument('--db',default='.state/prices.sqlite3')
    parser.add_argument('--output')
    parser.add_argument('--runs',default='.state/runs')
    parser.add_argument('--experiments',default='.state/experiments')
    parser.add_argument('--variant',choices=list(VARIANTS),default='baseline')
    args=parser.parse_args();s=None
    try:
        cfg=json.loads(Path(args.config).read_text());s=Store(args.db)
        if args.command=='backfill':result=backfill_year(s,cfg)
        elif args.command=='events':result={'status':'completed','sources':fetch_distributions(s,cfg['data_start'],cfg['end']),
                                          'reconciliation':reconcile_distributions(s,cfg['data_start'],cfg['end'])}
        else:
            reconciliation=reconcile_distributions(s,cfg['data_start'],cfg['end'])
            result=run_year(s,cfg,variant=args.variant);result['reconciliation']=reconciliation
    except Exception as exc:
        result={'schema_version':1,'generated_at':datetime.now(timezone.utc).isoformat(),'research_model_id':'F',
                'status':'error','classification':'retrospective_diagnostic','promotion_allowed':False,'experiments':[],
                'run_error':str(exc),'active_strategy':None}
    finally:
        if s:s.close()
    from .__main__ import write_json
    output=Path(args.output or (('site/annual-backtest.json' if args.variant=='baseline' else f'site/annual-{args.variant}.json') if args.command=='research' else f'site/annual-{args.command}.json'))
    if args.command=='research':
        from .reporting import record_run
        from .optimizer import code_version
        import os
        result.setdefault('version',code_version())
        run=record_run(result,'annual-research',args.experiments,args.runs,output.parent,os.environ.get('GITHUB_STEP_SUMMARY'))
        result['run_id']=run['run_id']
    write_json(output,result)
    print(json.dumps({k:result.get(k) for k in ('status','completed_dates','last_completed','http_requests','run_id','run_error','elapsed_seconds')},ensure_ascii=False),flush=True)
    if result['status']=='error':raise SystemExit(1)


if __name__=='__main__':main()
