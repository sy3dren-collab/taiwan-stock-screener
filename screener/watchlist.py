"""Ranked research observations, never portfolio entry signals."""
from dataclasses import asdict,replace
import json
from pathlib import Path
from statistics import mean

from .annual import GuardedSignals
from .naked import NakedParameters,evaluate
from .quality import actions


def evaluator(config,include_bars=True,strict_parameters=None):
    def observe(bars,model,p):
        today,previous=bars[-1],bars[-2]
        base=bars[-61:-1]
        upper,lower=max(b.high for b in base),min(b.low for b in base)
        width=upper/lower-1
        drift=abs(mean(b.close for b in base[-10:])/mean(b.close for b in base[:10])-1)
        ma=mean(b.close for b in bars[-20:])
        prior_ma=mean(b.close for b in bars[-25:-5])
        slope=ma/prior_ma-1
        average_range=mean((b.high-b.low)/b.close for b in bars[-20:])
        support=min(b.low for b in bars[-10:])
        distance=today.close/support-1
        momentum=today.close/bars[-6].close-1
        if (width>config['range_width'] or drift>config['range_drift_max']
            or distance>config['support_distance_max']
            or today.close/ma-1<config['ma_distance_min']
            or momentum<config['five_day_return_min']
            or slope<config['minimum_ma_slope']
            or average_range>config['maximum_average_daily_range']):return None
        event=None
        # Each historical event has its own preceding consolidation range.
        for i in reversed(range(len(bars)-30,len(bars))):
            before=bars[i-60:i]
            if len(before)!=60:continue
            lo,hi=min(b.low for b in before),max(b.high for b in before)
            if hi/lo-1>config['range_width']:continue
            b=bars[i];vol=mean(x.volume for x in bars[i-20:i])
            if vol<=0 or b.close<=b.open or b.volume/vol<config['event_volume_multiple']:continue
            reclaim=b.low<lo*.995 and b.close>=lo*1.005
            breakout=bars[i-1].close<hi*1.005<=b.close
            level=lo if reclaim else hi
            if not(reclaim or breakout) or today.close<level*.98:continue
            if min(x.close for x in bars[i:])<level*.98:continue
            event=(b.date,'放量收復' if reclaim else '放量突破',b.volume/vol,len(bars)-1-i);break
        # Confirmation is evaluated with the unchanged full entry requirements.
        strict=evaluate(bars,'F',strict_parameters or p)
        stage='已符合研究進場條件' if strict else '事件後等待回測轉強' if event else '整理觀察，等待放量事件'
        waiting=[]
        if not event:waiting.append('等待至少1.2倍量的區間收復或突破事件')
        if not strict:waiting.append('尚未完整符合縮量回測、放量轉強、停損8%及最低1.5R條件；不得視為進場訊號')
        stop=support*(1-p.stop_buffer);target=max(upper,today.close)
        rr=(target-today.close)/(today.close-stop)
        display_support,display_stop,display_target,display_rr=(strict[k] for k in ('support','stop','target','reward_risk')) if strict else (support,stop,target,rr)
        event_score=35*(1-event[3]/40) if event else 0
        trend_score=10*min(1,slope/.03)+(10 if ma>=mean(b.close for b in bars[-60:]) else 0)
        stability_score=20*(1-average_range/config['maximum_average_daily_range'])
        score=round((100 if strict else 0)+event_score+trend_score+stability_score+30*(1-distance/config['support_distance_max'])+20*(1-width/config['range_width']),6)
        return {'market':today.market,'code':today.code,'name':today.name,'date':today.date,
                'close':today.close,'change_pct':100*(today.close/previous.close-1),'support':display_support,
                'stop':display_stop,'target':display_target,'reward_risk':display_rr,'score':score,'variant':stage,
                'risk_fraction':(today.close-display_stop)/today.close,
                'observation_only':True,'entry_confirmed':bool(strict),'waiting_conditions':waiting,
                'chart_price_basis':'當日已知公司行動調整；研究觀察，不是買進指示',
                'reasons':[f'20日均線近5日變動 {slope:.1%}；近20日日均振幅 {average_range:.1%}',f'60日整理振幅 {width:.1%}、首尾均價漂移 {drift:.1%}',
                           f'距近10日低點 {distance:.1%}；近5日漲跌 {momentum:.1%}',
                           f'{event[0]} {event[1]}，當日量比 {event[2]:.2f}' if event else '尚未確認放量事件，僅列較早期整理觀察',
                           *waiting],
                'bars':[asdict(b) for b in bars[-60:]] if include_bars else []}
    return observe


def provider(store,p,sessions,include_bars=True):
    config=json.loads(Path('watchlist.json').read_text())
    if config['target_count']!=10:raise ValueError('目前每日觀察上限為10檔')
    admission=replace(p,minimum_price=config['minimum_price'],minimum_turnover=config['minimum_turnover'])
    barriers=[json.loads(r[0]) for r in store.db.execute('SELECT payload FROM distribution_rows') if not json.loads(r[0])['supported']]
    return GuardedSignals(admission,actions(store),sessions,barriers,evaluator(config,include_bars,p))


def build(store,asof,p):
    from .distributions import event_tables
    event_tables(store)
    sessions=[r[0] for r in store.db.execute('SELECT DISTINCT date FROM bars WHERE date<=? ORDER BY date',(asof,))]
    if not sessions:return {'candidates':[],'qualified_count':0,'target_count':10}
    first=sessions[max(0,len(sessions)-p.lookback-1)]
    from .data import Bar
    histories={}
    for row in store.db.execute('SELECT * FROM bars WHERE date BETWEEN ? AND ? ORDER BY date,market,code',(first,asof)):
        b=Bar(*row);histories.setdefault((b.market,b.code),[]).append(b)
    signals=provider(store,p,sessions)
    view=signals(histories,asof)
    view.update(qualified_count=signals.daily[-1].get('signals',0),target_count=10,
                observation_only=True,shortfall=len(view['candidates'])<10,
                message='每日研究觀察前10名；未確認進場者須等待，不代表已驗證獲利',
                parameters=json.loads(Path('watchlist.json').read_text()))
    return view
