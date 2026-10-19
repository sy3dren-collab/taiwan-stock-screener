"""Rolling calendar-year comparison; frozen candidates and chronological diagnostics."""
from bisect import bisect_right
from collections import defaultdict
from dataclasses import asdict
from datetime import date, timedelta
import logging
from statistics import mean

from .backtest import simulate
from .data import DataError
from .models import MODELS, required_bars, screen_model
from .refinements import WEAKNESSES, CHANGES, refined_screen


def verify_coverage(store, histories, start, end, required):
    dates=sorted({b.date for bars in histories.values() for b in bars if b.date<=end})
    prior=[d for d in dates if d<start]
    if len(prior)<required-1:
        raise DataError(f'{start} 之前暖機歷史不足 {required-1} 個交易日；請補齊官方資料')
    first=dates[0]
    checked={row[0] for row in store.db.execute('SELECT date FROM sessions WHERE date BETWEEN ? AND ?',(first,end))}
    day=date.fromisoformat(first);last=date.fromisoformat(end)
    while day<=last:
        if day.weekday()<5 and day.isoformat() not in checked:
            raise DataError(f'官方日期覆蓋有缺漏：{day}；不可把未抓取日期當作休市')
        day+=timedelta(days=1)
    rows=store.db.execute("""
        SELECT s.date,s.twse_count,s.tpex_count,
          SUM(CASE WHEN b.market='TWSE' THEN 1 ELSE 0 END),
          SUM(CASE WHEN b.market='TPEX' THEN 1 ELSE 0 END)
        FROM sessions s LEFT JOIN bars b ON b.date=s.date
        WHERE s.date BETWEEN ? AND ? GROUP BY s.date
        """,(first,end))
    for day,twse,tpex,actual_twse,actual_tpex in rows:
        if (twse,tpex)!=(actual_twse,actual_tpex) or bool(twse)!=bool(tpex):
            raise DataError(f'官方日期 {day} 行情筆數與完成紀錄不符；拒絕使用不完整歷史')
    return {'checked_from':first,'checked_through':end,'checked_weekdays':len(checked)}


def year_start(end):
    day=date.fromisoformat(end)
    try:previous=day.replace(year=day.year-1)
    except ValueError:previous=day.replace(year=day.year-1,day=28)
    return (previous+timedelta(days=1)).isoformat()


def validation_start(start):
    day=date.fromisoformat(start)
    months=day.year*12+day.month-1+8
    # Dates 29–31 are clamped to the last day of the destination month.
    y,m=divmod(months,12)
    next_month=date(y+(m==11),(m+1)%12+1,1)
    return date(y,m+1,min(day.day,(next_month-timedelta(days=1)).day)).isoformat()


def diagnose(report, histories):
    reasons=defaultdict(lambda:{'count':0,'net_pnl':0})
    variants=defaultdict(lambda:{'count':0,'net_pnl':0})
    months=defaultdict(lambda:{'count':0,'net_pnl':0})
    loss_streak=max_loss_streak=0
    for t in report['closed_trades']:
        for groups,key in ((reasons,t['exit_reason']),(variants,t['signal_variant']),(months,t['exit_date'][:7])):
            groups[key]['count']+=1;groups[key]['net_pnl']=round(groups[key]['net_pnl']+t['net_pnl'],2)
        loss_streak=loss_streak+1 if t['net_pnl']<0 else 0
        max_loss_streak=max(max_loss_streak,loss_streak)
        bars=[b for b in histories[(t['market'],t['code'])] if t['entry_date']<=b.date<t['exit_date']]
        t['maximum_favorable_excursion']=round(max([b.high/t['entry_price']-1 for b in bars]+[0]),6)
        t['maximum_adverse_excursion']=round(min([b.low/t['entry_price']-1 for b in bars]+[0]),6)
    return {'exit_reasons':dict(reasons),'signal_variants':dict(variants),'exit_months':dict(months),
            'longest_losing_streak':max_loss_streak,
            'mean_exposure':mean(max(0,min(1,1-p['cash']/p['equity'])) for p in report['equity_curve']),
            'note':'型態、出場原因與進場後最大有利／不利幅度僅作事後診斷，不參與當時訊號。'}


def summary(report):
    return {k:report[k] for k in ('start','end','simulated_sessions','closed_count','open_count','metrics')}


def verdict(development, validation):
    # No candidate is promoted automatically, even if it passes this descriptive screen.
    enough=all(w[v]['closed_count']>=30 for w in (development,validation) for v in ('baseline','candidate'))
    improves=all(w['candidate']['metrics']['total_return']>w['baseline']['metrics']['total_return'] and
                 w['candidate']['metrics']['max_drawdown']<=w['baseline']['metrics']['max_drawdown']
                 for w in (development,validation))
    profitable=validation['candidate']['metrics']['total_return']>0
    if not enough:return '樣本不足，保留研究候選'
    if improves and profitable:return '歷史分段表現改善，仍待未來資料驗證'
    return '尚未證明穩定改善，保留原版'


def run_research(histories,p,e,m,r,start=None,end=None):
    dates=sorted({b.date for bars in histories.values() for b in bars if not end or b.date<=end})
    if not dates:raise DataError('沒有可用的官方歷史行情')
    end=min(end or dates[-1],dates[-1]);start=start or year_start(end)
    if start>=end:raise DataError('回測期間須至少兩個交易日')
    required=max(required_bars(p,m,model) for model in MODELS)
    before=[d for d in dates if d<start]
    if len(before)<required-1:
        raise DataError(f'一年回測需要 {start} 前至少 {required-1} 個交易日暖機；請使用 update --start 補齊更早官方行情，不會縮短期間冒充一年')
    active=[d for d in dates if start<=d<=end]
    split=validation_start(start)
    dev=[d for d in active if d<split];valid=[d for d in active if d>=split]
    if len(dev)<20 or len(valid)<20:raise DataError('前八個月開發／後四個月驗證資料不足各 20 個交易日')
    # Reject missing weekdays: an unrecorded day is not silently assumed a holiday.
    # Caller checks the official sessions ledger for completeness before this function.
    indices={k:[b.date for b in bars] for k,bars in histories.items()}
    streams={model:{'baseline':{},'candidate':{}} for model in MODELS}
    for i,day in enumerate(active):
        known={k:bars[:bisect_right(indices[k],day)] for k,bars in histories.items()}
        for model in MODELS:
            streams[model]['baseline'][day]=screen_model(known,day,p,model,m,include_bars=False)
            streams[model]['candidate'][day]=refined_screen(known,day,p,model,m,r)
        if i%20==0:logging.warning('一年研究訊號 %s / %s：%s',i+1,len(active),day)
    models=[]
    for model in MODELS:
        reports={}
        for version in ('baseline','candidate'):
            cache=streams[model][version]
            callback=lambda known,day,params,cache=cache: cache[day]
            kwargs={'model_settings':m,'signal_function':callback,'refinement_settings':r if version=='candidate' else None}
            full=simulate(histories,p,e,model,start,end,**kwargs)
            full['diagnostics']=diagnose(full,histories)
            full['version']=version
            if version=='candidate':
                full['name']=MODELS[model]['name']+'｜改良候選 v1'
                full['description']=CHANGES[model]
            development=simulate(histories,p,e,model,dev[0],dev[-1],**kwargs)
            validation=simulate(histories,p,e,model,valid[0],valid[-1],**kwargs)
            reports[version]={'full':full,'development':summary(development),'validation':summary(validation)}
        base=reports['baseline']['full']
        development={v:reports[v]['development'] for v in reports}
        validation={v:reports[v]['validation'] for v in reports}
        base['experiment']={'candidate':reports['candidate']['full'], 'weaknesses':WEAKNESSES[model],
                            'changes':CHANGES[model], 'development':development,'validation':validation,
                            'assessment':verdict(development,validation), 'promoted':False}
        models.append(base)
    return {'status':'preliminary','price_basis':'unadjusted','strategy_parameters':asdict(p),'execution_parameters':asdict(e),
            'model_parameters':asdict(m),'refinement_parameters':asdict(r),'active_model':'trend_pullback','user_model':'user_range_reclaim',
            'requested_start':start,'requested_end':end,'models':models,
            'research_protocol':{'candidate_count_per_model':1,'parameter_search':False,'split':split,
                'development':'前八個日曆月','validation':'後四個日曆月；各段重新以現金開始，不承接開發段持倉',
                'selection':'不自動替換正式策略；描述性門檻：兩段報酬改善、回撤不增加，驗證段正報酬且每版每段至少 30 筆已平倉',
                'leakage_notice':'此前已看過末段 55 個交易日，因此這是回溯分段檢查，不是真正未見的樣本外驗證；未來實盤前向觀察仍待完成。',
                'limitations':['未還原權息及股息，除權息可能造成假訊號與假損益。','歷史包含當時出現的代號，未依目前上市名單回溯篩選；下市缺價仍無清算模型。','只涵蓋一年，不能推論跨市場循環穩健性。']}}
