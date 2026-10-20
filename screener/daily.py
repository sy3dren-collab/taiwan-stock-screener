"""One verified frozen strategy only; no actual order or broker interface."""
import argparse,json,hashlib,time
from dataclasses import asdict
from datetime import datetime,date,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .__main__ import default_end,update,write_json
from .data import Store,DataError,OfficialClient,URLS
from .execution import Execution,entry_plan,tick_price
from .naked import NakedParameters,NAMES,screen
from .naked_backtest import Risk,simulate
from .optimizer import code_version
from .quality import actions,audit_dataset


def approved(registry,frozen,final):
    if registry.get('mode')!='active' or not isinstance(registry.get('active_strategy'),str) or registry.get('active_strategy') not in NAMES:return '尚無通過驗證的策略'
    if not registry.get('approval_reference'):return '缺正式版本審核紀錄'
    if not frozen or not frozen.get('walk_forward_passed'):return '缺通過 Walk-Forward 的凍結候選'
    body={k:v for k,v in frozen.items() if k!='frozen_sha256'}
    if hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()!=frozen.get('frozen_sha256'):return '凍結參數雜湊不符'
    if frozen.get('execution')!=asdict(Execution(**json.loads(Path('execution.json').read_text()))):return '成交成本設定與凍結版本不同'
    if registry.get('frozen_version')!=frozen.get('frozen_sha256') or registry['active_strategy']!=frozen.get('model_id'):return '正式規則與凍結版本不一致'
    if final.get('status')!='completed' or not final.get('executed') or not final.get('result',{}).get('assessment',{}).get('passed'):return '最終樣本外未通過'
    if final['result'].get('frozen_sha256')!=frozen['frozen_sha256']:return '最終測試與凍結版本不一致'
    if code_version()['code_sha256']!=frozen['version']['code_sha256']:return '交易程式與凍結版本不同，禁止自動替換'
    return None


def read_optional(path):return json.loads(Path(path).read_text()) if Path(path).is_file() else {}


def produce(store,cfg,registry,frozen,final,end,offline=False,update_error=None):
    now=datetime.now(ZoneInfo('Asia/Taipei')).isoformat();p=NakedParameters(**cfg['signal']);e=Execution(**json.loads(Path('execution.json').read_text()))
    asof=store.db.execute('SELECT MAX(date) FROM bars WHERE date<=?',(end,)).fetchone()[0]
    result={'schema_version':1,'generated_at':now,'requested_through':end,'as_of':asof,'status':'ok','mode':'research',
            'active_strategy':None,'active_model':None,'candidates':[],'strategies':{},'parameters':asdict(p),
            'universe_count':0,'qualified_count':0,'sufficient_history_count':0,'shortfall':True,'warnings':[],
            'source_warnings':[],'errors':[],'sources':URLS,'message':'尚無通過驗證的策略','signal_status':'research_only','orders_enabled':False}
    if update_error or not asof or (date.fromisoformat(end)-date.fromisoformat(asof)).days>7:
        result.update(status='error',errors=[update_error or '沒有有效或足夠新近的官方行情']);return result
    result['universe_count']=store.db.execute('SELECT COUNT(*) FROM bars WHERE date=?',(asof,)).fetchone()[0]
    if offline:result['warnings'].append('離線讀取，未宣稱已重新更新官方行情')
    if asof!=end:result['warnings'].append(f'請求截至 {end}，最新官方行情 {asof}；請核對休市與資料公布狀態，不是今日新訊號')
    from .watchlist import build
    result['watchlist']=build(store,asof,p)
    reason=approved(registry,frozen,final)
    if reason:result['warnings'].append(reason);result['source_warnings']=result['warnings'][:];return result
    q=audit_dataset(store,{**cfg['study'],'as_of':asof})
    if not q.get('research_ready'):result['warnings']+=q['issues'];result['source_warnings']=result['warnings'][:];return result
    p=NakedParameters(**frozen['parameters']);result['parameters']=asdict(p);view=screen(store.histories(asof),asof,frozen['model_id'],p,actions(store),True)
    for c in view['candidates']:
        plan=entry_plan(c,e,p)
        plan['maximum_open']=min(plan['maximum_open'],tick_price(c['stop']/(1-p.max_risk)/(1+e.slippage_rate),False))
        plan['stop_rule']='盤中觸及結構停損即依模型出場；跳空採不利開盤，同根停損停利衝突先停損'
        plan['target_rule']='觸及結構目標可提前出場，不強迫持有滿5日；漲跌停／停牌可能延後'
        c['entry_plan']=plan;c['strategy_version']=frozen['frozen_sha256'];c['signal_status']='收盤確認，下一交易日仍須符合開盤及風險條件'
    view.update(name=NAMES[frozen['model_id']],description='已凍結且通過驗證的唯一策略；不提供自動下單',required_bars=p.lookback,shortfall=not view['candidates'])
    result.update(view,mode='active',active_strategy=frozen['model_id'],active_model=frozen['model_id'],strategies={frozen['model_id']:view},
                  message='今日無符合策略條件的股票' if not view['candidates'] else '收盤確認候選；非成交保證',strategy_version=frozen['frozen_sha256'])
    result['source_warnings']=result['warnings'][:]
    return result


def promote(registry_path,frozen,final,quality,approval_reference):
    if not approval_reference:raise DataError('須有明確審核紀錄，不得自動覆寫正式版本')
    candidate={'mode':'active','active_strategy':frozen.get('model_id'),'frozen_version':frozen.get('frozen_sha256'),'approval_reference':approval_reference}
    reason=approved(candidate,frozen,final)
    if reason or quality.get('status')!='ready':raise DataError(reason or '正式資料驗證未通過')
    original=read_optional(registry_path);versions=Path(registry_path).parent/'strategies';versions.mkdir(parents=True,exist_ok=True)
    frozen_file=versions/f"{frozen['frozen_sha256']}.json";final_file=versions/f"{frozen['frozen_sha256']}.final.json"
    for path,payload in ((frozen_file,frozen),(final_file,final)):
        if path.exists() and json.loads(path.read_text())!=payload:raise DataError('正式版本檔不可覆寫')
        write_json(path,payload)
    candidate.update(schema_version=1,automatic_promotion=False,archived=original.get('archived',[]),approved_at=datetime.now(ZoneInfo('Asia/Taipei')).isoformat(),frozen_file=str(frozen_file),final_file=str(final_file))
    write_json(Path(registry_path),candidate)


def paper(store,cfg,registry,frozen,final,path,end):
    reason=approved(registry,frozen,final)
    if reason:return {'status':'inactive','reason':reason,'orders_enabled':False}
    start=registry['approved_at'][:10];asof=store.db.execute('SELECT MAX(date) FROM bars WHERE date<=?',(end,)).fetchone()[0]
    q=audit_dataset(store,{**cfg['study'],'as_of':asof or end})
    if not q.get('research_ready'):return {'status':'blocked','reason':';'.join(q['issues']),'orders_enabled':False}
    if not asof or asof<start:return {'status':'pending','reason':'尚無正式凍結後行情','orders_enabled':False}
    records=Path(path);records.parent.mkdir(parents=True,exist_ok=True)
    old=[json.loads(line) for line in records.read_text().splitlines()] if records.exists() else []
    version=frozen['frozen_sha256']
    if old and any(row['version']!=version for row in old):raise DataError('前瞻觀察不同版本須使用不同帳本，禁止覆寫過往績效')
    if len({b.date for bars in store.histories(asof).values() for b in bars if start<=b.date<=asof})<2:return {'status':'pending','reason':'前瞻有效交易日不足兩日','orders_enabled':False}
    report=simulate(store.histories(asof),NakedParameters(**frozen['parameters']),Execution(**frozen['execution']),Risk(**frozen['risk']),frozen['model_id'],start,asof,actions(store),deadline=time.monotonic()+cfg['budget']['max_seconds'])
    if not any(row['as_of']==asof for row in old):
        with records.open('a') as f:f.write(json.dumps({'version':version,'as_of':asof,'recorded_at':datetime.now(ZoneInfo('Asia/Taipei')).isoformat(),'metrics':report['metrics']},ensure_ascii=False,allow_nan=False)+'\n')
    return {'status':'paper_model','version':version,'orders_enabled':False,'forward_since':start,'report':report,'note':'凍結後行情的前瞻模型觀察，非真實委託成交'}


def main():
    p=argparse.ArgumentParser(description='唯一凍結策略每日報告、晉級及無下單紙上觀察')
    p.add_argument('command',choices=['screen','promote','paper']);p.add_argument('--db',default='.state/prices.sqlite3');p.add_argument('--config',default='naked_k.json')
    p.add_argument('--registry',default='strategy_registry.json');p.add_argument('--frozen');p.add_argument('--final')
    p.add_argument('--output');p.add_argument('--offline',action='store_true');p.add_argument('--approval-reference');p.add_argument('--paper-ledger')
    a=p.parse_args();output=a.output or {'screen':'site/results.json','paper':'site/paper.json','promote':'.state/promotion-status.json'}[a.command];s=None
    try:
        cfg=json.loads(Path(a.config).read_text());Path(a.db).parent.mkdir(parents=True,exist_ok=True);s=Store(a.db)
        registry=read_optional(a.registry)
        proposal=a.command=='promote'
        frozen=read_optional(a.frozen or ('.state/experiments/frozen_candidate.json' if proposal else registry.get('frozen_file','.state/missing-approved-strategy.json')))
        final=read_optional(a.final or ('site/final-test.json' if proposal else registry.get('final_file','.state/missing-approved-final.json')));error=None
        if a.command=='screen':
            end=default_end()
            if not a.offline:
                try:
                    import time
                    # Eight refreshed dates × two markets × up to three tries.
                    # Leave the final fresh-cache retry reachable in this caller.
                    client=OfficialClient(delay=2,retries=3,request_budget=50,deadline=time.monotonic()+600)
                    start=end-timedelta(days=25) if not s.last_checked() else None
                    update(s,client,end,180,start)
                except Exception as exc:error=str(exc)
            result=produce(s,cfg,registry,frozen,final,end.isoformat(),a.offline,error)
            write_json(Path(output).with_name('active-performance.json'),final if result['mode']=='active' else {'status':'inactive','executed':False})
        elif a.command=='promote':
            promote(a.registry,frozen,final,audit_dataset(s,cfg['study']),a.approval_reference);result={'status':'approved','orders_enabled':False}
        else:result=paper(s,cfg,registry,frozen,final,a.paper_ledger or f".state/paper/{registry.get('frozen_version','inactive')}.jsonl",default_end().isoformat())
    except Exception as exc:result={'schema_version':1,'status':'error','mode':'research','candidates':[],'as_of':None,'errors':[str(exc)],'orders_enabled':False}
    finally:
        if s:s.close()
    write_json(Path(output),result)
    if result.get('status')=='error':raise SystemExit(1)

if __name__=='__main__':main()
