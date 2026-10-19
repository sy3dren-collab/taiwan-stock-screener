"""Bounded experiments; research never writes the production strategy registry."""
from dataclasses import asdict,replace
from datetime import datetime,timezone,timedelta,date
import argparse,hashlib,json,subprocess,time,os
from pathlib import Path
from statistics import mean

from .data import Store,DataError
from .execution import Execution
from .naked import NakedParameters,NAMES
from .naked_backtest import Risk,simulate,ResearchBudgetExceeded
from .quality import audit_dataset,actions
from .validation import Gates,folds,assess,final_once,holdout_reason


def code_version():
    files=['data.py','quality.py','naked.py','naked_backtest.py','performance.py','validation.py','optimizer.py','execution.py','daily.py','strategy.py','fusion.py','annual.py','distributions.py']
    digest=hashlib.sha256()
    for f in files:digest.update(Path(__file__).with_name(f).read_bytes())
    git=subprocess.run(['git','rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
    dirty=subprocess.run(['git','status','--porcelain','--untracked-files=all','--','screener','naked_k.json','execution.json','annual_research.json'],capture_output=True,text=True,check=True)
    return {'git_commit':git,'code_sha256':digest.hexdigest(),'working_tree_dirty':bool(dirty.stdout.strip())}


def benchmark(histories,p,e,risk,fold,events,deadline):
    all_dates=sorted({b.date for bars in histories.values() for b in bars});start=fold['validation_start']
    before=max(d for d in all_dates if d<start);eligible=[]
    for key,bars in histories.items():
        known=[b for b in bars if b.date<=before]
        if len(known)<p.liquidity_days or known[-1].date!=before or known[-1].close<p.minimum_price:continue
        recent=known[-p.liquidity_days:]
        if any(b.turnover is None for b in recent):continue
        amount=mean(b.turnover for b in recent)
        if amount>=p.minimum_turnover:eligible.append((amount,key))
    eligible.sort(key=lambda x:(-x[0],x[1]));pool=[key for _,key in eligible[:e.max_positions]]
    if len(pool)<e.max_positions:raise DataError('當時合格買入持有參考不足五檔，禁止省略公平比較')
    def signals(known,day):
        candidates=[]
        if day==start:
            for key in pool:
                bars=known.get(key,[])
                if not bars or bars[-1].date!=day:continue
                b=bars[-1];candidates.append({'market':b.market,'code':b.code,'name':b.name,'date':day,'close':b.close,
                    'stop':b.close*.0001,'target':b.close*1000000,'metrics':{'average_volume':mean(x.volume for x in bars[-p.liquidity_days:])},'reasons':['驗證前已知流動性前五普通股買入持有參考']})
        return {'candidates':candidates}
    result=simulate(histories,p,e,risk,'buy_hold',start,fold['validation_end'],events,deadline,signals,benchmark=True)
    result['benchmark_note']='當時流動性前五普通股等權、同本金與成本、次日開盤；期末未平倉採扣估計賣出成本估值，非大盤指數'
    return result


def evaluate_candidate(histories,p,e,risk,model,plan,events,deadline):
    train=[];validation=[]
    for f in plan:
        t=simulate(histories,p,e,risk,model,f['train_start'],f['train_end'],events,deadline,entry_cutoff=f['train_entry_cutoff'])
        if t['open_positions']:raise DataError('Purging 後訓練段仍有不可成交持倉，不可隱藏未結束標籤')
        v=simulate(histories,p,e,risk,model,f['validation_start'],f['validation_end'],events,deadline,entry_cutoff=f['validation_entry_cutoff'])
        if v['open_positions']:raise DataError('驗證段仍有延遲出場持倉，拒絕跨折假設回到現金')
        train.append(t);validation.append(v)
    return {'training':train,'validation':validation}


def next_hypothesis(p,training,iteration):
    # Only the earliest training fold proposes the rule. Never examine reserved-year outcomes.
    trades=training[0]['closed_trades'] if training else []
    stops=sum('停損' in t['exit_reason'] for t in trades)
    expiries=sum('到期' in t['exit_reason'] for t in trades)
    if iteration%2==1 and stops>=expiries:
        value=max(.005,p.support_tolerance*.9)
        return replace(p,support_tolerance=value),'support_tolerance',f'最早訓練段停損{stops}筆、到期{expiries}筆：只測試縮小回測支撐容許距離10%'
    return replace(p,close_location=min(.9,p.close_location+.05)),'close_location',f'最早訓練段停損{stops}筆、到期{expiries}筆：只提高收盤位置門檻0.05，確認轉強'


def research(store,cfg,output_dir,max_experiments=None,seconds=None,evaluator=evaluate_candidate,benchmark_function=benchmark):
    p=NakedParameters(**cfg['signal']);risk=Risk(**cfg['risk']);e=Execution(**json.loads(Path('execution.json').read_text()));g=Gates(**cfg['gates'])
    budget=cfg['budget'];limit=max_experiments if max_experiments is not None else budget['max_experiments'];duration=seconds if seconds is not None else budget['max_seconds']
    if not isinstance(limit,int) or not 1<=limit<=min(100,budget['max_experiments']) or not 0<duration<=min(1800,budget['max_seconds']):raise ValueError('實驗次數或時間超出預設預算')
    quality=audit_dataset(store,cfg['study']);research_end=(date.fromisoformat(cfg['study']['holdout_start'])-timedelta(days=1)).isoformat()
    training_quality=audit_dataset(store,{**cfg['study'],'as_of':research_end})
    version=code_version();now=datetime.now(timezone.utc).isoformat()
    result={'schema_version':1,'generated_at':now,'status':'blocked','mode':'research','active_strategy':None,
            'message':'尚無通過驗證的策略','research_model_id':'F','data_quality':quality,'training_data_quality':training_quality,'version':version,'experiments':[],
            'candidates':[{'model_id':k,'name':v,'status':'blocked','metrics':None} for k,v in NAMES.items()],
            'final_holdout':{'status':'blocked','executed':False,'reason':holdout_reason(cfg['study'],json.loads(Path('docs/data-exposure.json').read_text()))},
            'budget':{'maximum_experiments':limit,'maximum_seconds':duration},'paper_trading':{'status':'inactive','orders_enabled':False}}
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
    if not training_quality.get('research_ready',training_quality['status']=='ready'):
        result['stop_reason']='data_quality';return result
    research_end=(date.fromisoformat(cfg['study']['holdout_start'])-timedelta(days=1)).isoformat()
    histories=store.histories(research_end) # Reserved-year prices never enter the optimizer.
    plan=folds([b.date for bars in histories.values() for b in bars],cfg['study'])
    if len(plan)<g.minimum_folds:result['stop_reason']='insufficient_walk_forward_history';return result
    events=[a for a in actions(store) if a.effective_date<=research_end and a.announced_date<=research_end]
    deadline=time.monotonic()+duration;start_clock=time.monotonic();benchmarks=None;retained={};best=None;serial=0
    try:
        benchmarks=[benchmark_function(histories,p,e,risk,f,events,deadline) for f in plan]
        states={model:{'current':p,'baseline':None,'previous':None,'base_report':None,'failed':False} for model in NAMES}
        for iteration in range(3):
            for model in NAMES:
                state=states[model]
                if state['failed']:continue
                current,baseline,previous,base_report=(state[k] for k in ('current','baseline','previous','base_report'))
                if serial>=limit or time.monotonic()>=deadline:break
                serial+=1;reason='單一合併策略固定基準，使用相同資金、成本、資料及時序切分';changed=[]
                baseline_parameters=asdict(current)
                if iteration:
                    current,field,reason=next_hypothesis(current,previous['training'],iteration);changed=[field]
                identifier=f'{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")}-{model}-{iteration}'
                record={'experiment_id':identifier,'model_id':model,'iteration':iteration,'changed_rules':changed,'reason':reason,
                        'parameters':asdict(current),'baseline_parameters':baseline_parameters,'risk':asdict(risk),'execution':asdict(e),'data_sha256':training_quality['data_sha256'],
                        'version':version,'folds':plan,'retained':False,'status':'running'}
                try:
                    report=evaluator(histories,current,e,risk,model,plan,events,deadline)
                    if baseline is None:baseline=report['validation'];base_report=report
                    gate=assess(report['validation'],baseline if iteration else None,benchmarks,g)
                    record.update(status='completed',results=report,assessment=gate)
                    # The finite same-universe stress and +/-10% proximity checks are mandatory before retaining.
                    robustness=[]
                    if gate['passed']:
                        stress=replace(e,fee_rate=e.fee_rate*g.stress_cost_multiple,slippage_rate=e.slippage_rate*g.stress_cost_multiple)
                        stress_report=evaluator(histories,current,stress,risk,model,plan,events,deadline)
                        robustness.append({'kind':'double_costs','passed':all(r['metrics']['net_return']>0 for r in stress_report['validation']), 'results':stress_report})
                        for factor in (.9,1.1):
                            neighbor=replace(current,support_tolerance=current.support_tolerance*factor)
                            nr=evaluator(histories,neighbor,e,risk,model,plan,events,deadline)
                            robustness.append({'kind':f'support_tolerance_{factor:g}','passed':all(r['metrics']['net_return']>0 for r in nr['validation']),'results':nr})
                        gate['passed']=all(x['passed'] for x in robustness)
                        if not gate['passed']:gate['reasons'].append('成本或參數微擾不穩健')
                    record['robustness']=robustness
                    if gate['passed']:
                        score=(min(r['metrics']['net_return'] for r in report['validation']),gate['mean_validation_return'])
                        if model not in retained or score>retained[model]['score']:
                            record['retained']=True;retained[model]={'score':score,'record':record}
                        if best is None or score>best['score']:best={'score':score,'record':record}
                    if record['retained']:previous=report
                    else:
                        kept=retained.get(model)
                        current=NakedParameters(**kept['record']['parameters']) if kept else p
                        previous=kept['record']['results'] if kept else base_report
                except ResearchBudgetExceeded as exc:
                    record.update(status='budget_exhausted',error=str(exc));result['stop_reason']='resource_budget'
                except Exception as exc:record.update(status='error',error=str(exc))
                (out/f'{identifier}.json').write_text(json.dumps(record,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
                compact={k:v for k,v in record.items() if k not in ('results','robustness')}
                with (out/'ledger.jsonl').open('a') as f:f.write(json.dumps(compact,ensure_ascii=False,allow_nan=False)+'\n')
                result['experiments'].append(compact)
                state.update(current=current,baseline=baseline,previous=previous,base_report=base_report)
                if record['status']=='error':state['failed']=True
                if record['status']=='budget_exhausted':deadline=time.monotonic();break
    except ResearchBudgetExceeded:result['stop_reason']='resource_budget'
    except Exception as exc:result.update(run_error=str(exc),stop_reason='data_or_execution_error')
    result['status']='error' if result.get('run_error') else 'completed';result['stop_reason']=result.get('stop_reason','resource_budget' if time.monotonic()>=deadline else 'experiment_limit' if serial>=limit else 'planned_rounds_complete')
    result['budget']['used_experiments']=serial;result['budget']['elapsed_seconds']=round(time.monotonic()-start_clock,3)
    for row in result['candidates']:
        records=[x for x in result['experiments'] if x['model_id']==row['model_id']]
        row.update(status='not_qualified' if records else 'not_evaluated',experiments=len(records))
        if row['model_id'] in retained:row.update(status='walk_forward_candidate',metrics=retained[row['model_id']]['record']['assessment'])
    baseline_models={x['model_id'] for x in result['experiments'] if x['iteration']==0 and x['status']=='completed'}
    result['comparison_status']='complete' if baseline_models==set(NAMES) else 'incomplete'
    if best and result['comparison_status']=='complete':
        frozen={'model_id':best['record']['model_id'],'parameters':best['record']['parameters'],'risk':asdict(risk),'version':version,
                'data_sha256':training_quality['data_sha256'],'execution':asdict(e),'gates':asdict(g),'study':cfg['study'],'baseline_parameters':asdict(p),'walk_forward_passed':True,'source_experiment':best['record']['experiment_id']}
        frozen['frozen_sha256']=hashlib.sha256(json.dumps(frozen,sort_keys=True).encode()).hexdigest()
        (out/'frozen_candidate.json').write_text(json.dumps(frozen,ensure_ascii=False,indent=2)+'\n')
        result['frozen_candidate']=frozen;result['message']='候選已凍結，仍未通過最終樣本外；正式策略保持停用'
    return result


def main():
    parser=argparse.ArgumentParser(description='有界裸 K 自動研究，不覆寫正式策略')
    parser.add_argument('command',choices=['research','final-test']);parser.add_argument('--db',default='.state/prices.sqlite3');parser.add_argument('--config',default='naked_k.json')
    parser.add_argument('--output');parser.add_argument('--experiments',default='.state/experiments');parser.add_argument('--max-experiments',type=int);parser.add_argument('--seconds',type=float)
    parser.add_argument('--runs',default='.state/runs')
    a=parser.parse_args();s=None
    try:
        cfg=json.loads(Path(a.config).read_text());s=Store(a.db)
        if a.command=='research':result=research(s,cfg,a.experiments,a.max_experiments,a.seconds)
        else:
            quality=audit_dataset(s,cfg['study']);p=Path(a.experiments)/'frozen_candidate.json';frozen=json.loads(p.read_text()) if p.exists() else None
            def execute():
                if frozen['version']['code_sha256']!=code_version()['code_sha256'] or frozen['data_sha256']!=audit_dataset(s,{**cfg['study'],'as_of':(date.fromisoformat(cfg['study']['holdout_start'])-timedelta(days=1)).isoformat()})['data_sha256']:raise DataError('凍結程式或資料指紋已改變，禁止換版本重測')
                if frozen['study']!=cfg['study']:raise DataError('封存期間或研究設定與凍結版本不同')
                hist=s.histories(cfg['study']['holdout_end']);p=NakedParameters(**frozen['parameters']);e=Execution(**frozen['execution']);risk=Risk(**frozen['risk']);ev=actions(s);deadline=time.monotonic()+cfg['budget']['max_seconds']
                strategy=simulate(hist,p,e,risk,frozen['model_id'],cfg['study']['holdout_start'],cfg['study']['holdout_end'],ev,deadline)
                baseline=simulate(hist,NakedParameters(**frozen['baseline_parameters']),e,risk,frozen['model_id'],cfg['study']['holdout_start'],cfg['study']['holdout_end'],ev,deadline)
                ref=benchmark(hist,p,e,risk,{'validation_start':cfg['study']['holdout_start'],'validation_end':cfg['study']['holdout_end']},ev,deadline)
                final_gates=replace(Gates(**frozen['gates']),minimum_folds=1)
                gate=assess([strategy],[baseline] if frozen['parameters']!=frozen['baseline_parameters'] else None,[ref],final_gates)
                return {'strategy':strategy,'baseline':baseline,'benchmark':ref,'assessment':gate,'data_sha256':quality['data_sha256'],'frozen_sha256':frozen['frozen_sha256']}
            if frozen and frozen.get('model_id') not in NAMES:result={'status':'blocked','executed':False,'reason':'封存候選不是目前唯一合併策略，禁止使用舊候選'}
            else:result=final_once(cfg['study'],json.loads(Path('docs/data-exposure.json').read_text()),frozen,quality,Path(a.experiments)/'final-test-consumed.json',execute)
    except Exception as exc:
        result={'schema_version':1,'status':'error','mode':'research','research_model_id':'F','experiments':[],'run_error':str(exc),'executed':False,'version':code_version()}
    finally:
        if s:s.close()
    from .__main__ import write_json
    from .reporting import record_run
    result.setdefault('version',code_version());result.setdefault('research_model_id','F')
    run=record_run(result,a.command,a.experiments,a.runs,Path(a.output).parent if a.output else 'site',os.environ.get('GITHUB_STEP_SUMMARY'))
    result.update(run_id=run['run_id'],history_url='research-history.json')
    write_json(Path(a.output or ('site/research.json' if a.command=='research' else 'site/final-test.json')),result)
    if result.get('status')=='error':raise SystemExit(1)

if __name__=='__main__':main()
