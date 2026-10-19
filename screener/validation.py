"""Chronological folds, conservative gates and one-use holdout execution."""
from dataclasses import dataclass,asdict
import json,math
from pathlib import Path
from statistics import mean

@dataclass(frozen=True)
class Gates:
    minimum_folds:int=3
    minimum_trades:int=60
    minimum_fold_trades:int=10
    max_drawdown:float=.15
    minimum_profit_factor:float=1.2
    minimum_positive_folds:float=.67
    maximum_top_two_profit_share:float=.5
    target_win_rate:float=.85
    stress_cost_multiple:float=2
    def __post_init__(self):
        for key,value in asdict(self).items():
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:raise ValueError('晉級門檻須為正有限數值')
            if key in ('minimum_folds','minimum_trades','minimum_fold_trades') and not isinstance(value,int):raise ValueError('樣本門檻須為整數')
        if any(getattr(self,k)>1 for k in ('max_drawdown','minimum_positive_folds','maximum_top_two_profit_share','target_win_rate')) or self.stress_cost_multiple<1:raise ValueError('比例或成本壓力倍數不合法')


def folds(dates,study):
    dates=sorted(set(d for d in dates if study['analysis_start']<=d<study['holdout_start']))
    train=study['train_sessions'];valid=study['validation_sessions'];step=study['step_sessions'];purge=study['purge_sessions'];embargo=study['embargo_sessions']
    if any(isinstance(v,bool) or not isinstance(v,int) or v<=0 for v in (train,valid,step,purge,embargo)) or train<=purge or valid<=purge:raise ValueError('時間切分與 Purging 設定不合法')
    out=[];offset=0
    while offset+train+purge+embargo+valid<=len(dates):
        t=dates[offset:offset+train];v=dates[offset+train+purge+embargo:offset+train+purge+embargo+valid]
        out.append({'train_start':t[0],'train_end':t[-1],'train_entry_cutoff':t[-purge-1],
                    'validation_start':v[0],'validation_end':v[-1],'validation_entry_cutoff':v[-purge-1],
                    'purged_sessions':purge,'embargo_sessions':embargo})
        offset+=step
    return out


def assess(reports,baseline,benchmark,gates:Gates):
    trades=[t for r in reports for t in r['closed_trades']];reasons=[]
    returns=[r['metrics']['net_return'] for r in reports]
    profit=sum(max(t['net_pnl'],0) for t in trades);loss=-sum(min(t['net_pnl'],0) for t in trades)
    pf=profit/loss if loss else None
    top=sum(sorted((max(t['net_pnl'],0) for t in trades),reverse=True)[:2])/profit if profit else 1
    if len(reports)<gates.minimum_folds:reasons.append('Walk-Forward 折數不足')
    if len(trades)<gates.minimum_trades or any(r['metrics']['closed_count']<gates.minimum_fold_trades for r in reports):reasons.append('交易樣本不足')
    if not returns or mean(returns)<=0 or not trades or mean(t['net_pnl'] for t in trades)<=0:reasons.append('驗證淨報酬或期望值未為正')
    if returns and sum(x>0 for x in returns)/len(returns)<gates.minimum_positive_folds:reasons.append('跨期間不穩定')
    if any(r['metrics']['max_drawdown']>gates.max_drawdown for r in reports):reasons.append('回撤超限')
    if loss and pf<gates.minimum_profit_factor or not profit:reasons.append('獲利因子不足')
    if top>gates.maximum_top_two_profit_share:reasons.append('獲利過度集中一兩筆')
    if baseline and returns and mean(returns)<=mean(r['metrics']['net_return'] for r in baseline):reasons.append('未優於同條件基準')
    if benchmark and returns and mean(returns)<=mean(r['metrics']['net_return'] for r in benchmark):reasons.append('未優於當時流動性前五檔買入持有參考')
    return {'passed':not reasons,'reasons':reasons,'folds':len(reports),'closed_count':len(trades),
            'mean_validation_return':mean(returns) if returns else None,'expectancy':mean(t['net_pnl'] for t in trades) if trades else None,
            'profit_factor':pf,'top_two_profit_share':top,'target_win_rate':gates.target_win_rate,
            'target_is_gate':False,'note':'各折全現金重啟，不把平均或相加報酬當成連續投資組合年報酬'}


def holdout_reason(study,exposures):
    if study.get('holdout_status')!='pristine':return '封存測試集非未見資料，禁止宣稱獨立樣本外'
    for e in exposures['exposures']:
        if e['start']<=study['holdout_end'] and e['end']>=study['holdout_start']:return '封存期間與既知績效資料重疊，禁止重測調參'
    return None


def final_once(study,exposures,frozen,quality,marker,execute):
    reason=holdout_reason(study,exposures)
    if reason:return {'status':'blocked','reason':reason,'executed':False}
    if quality['status']!='ready' or not frozen or not frozen.get('walk_forward_passed'):return {'status':'blocked','reason':'資料或凍結候選未通過','executed':False}
    marker=Path(marker);marker.parent.mkdir(parents=True,exist_ok=True)
    claim={'frozen_sha256':frozen['frozen_sha256'],'start':study['holdout_start'],'end':study['holdout_end'],'status':'consumed'}
    try:
        with marker.open('x') as f:json.dump(claim,f)
    except FileExistsError:return {'status':'blocked','reason':'最終測試已使用，僅可讀取原結果，不得重跑調參','executed':False}
    # Claim before execution: even a failed test cannot be silently replayed as a fresh test.
    try:result=execute()
    except Exception as exc:return {**claim,'status':'error','executed':True,'reason':str(exc)}
    return {**claim,'status':'completed','executed':True,'result':result}
