"""One current fusion strategy and archived price-structure regressions."""
from dataclasses import asdict, dataclass, fields
import math
from statistics import mean, median

from .data import Bar
from .strategy import pivots
from .fusion import MODEL_ID,MODEL_NAME,pattern as fusion_pattern

NAMES={MODEL_ID:MODEL_NAME}
ARCHIVED_NAMES={'A':'上升結構回調','B':'盤整突破回測','C':'多次支撐反轉'}

@dataclass(frozen=True)
class NakedParameters:
    lookback:int=100
    structure_days:int=90
    pivot_radius:int=2
    pullback_days:int=5
    range_days:int=60
    event_days:int=15
    range_width:float=.25
    support_tolerance:float=.02
    confirmation_buffer:float=.005
    close_location:float=.7
    stop_buffer:float=.005
    minimum_price:float=20
    minimum_turnover:float=50000000
    liquidity_days:int=20
    min_reward_risk:float=1.5
    max_risk:float=.08
    support_touches:int=3
    touch_spacing:int=5
    range_edge_days:int=10
    range_drift_max:float=.08
    event_volume_multiple:float=1.5
    entry_volume_multiple:float=1.2
    pullback_volume_max:float=.8
    minimum_break_fraction:float=.005
    maximum_break_fraction:float=.08
    minimum_event_age:int=2
    extension_max:float=.04

    def __post_init__(self):
        integers={'lookback','structure_days','pivot_radius','pullback_days','range_days','event_days','liquidity_days','support_touches','touch_spacing','range_edge_days','minimum_event_age'}
        for f in fields(self):
            v=getattr(self,f.name)
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0:raise ValueError(f'{f.name} 須為正有限數值')
            if f.name in integers and not isinstance(v,int):raise ValueError(f'{f.name} 須為正整數')
        if self.lookback<max(self.structure_days,self.range_days+self.event_days,self.liquidity_days)+1:raise ValueError('lookback 不足以觀察完整結構')
        if self.structure_days<2*self.pivot_radius+5 or self.support_touches<2:raise ValueError('結構確認日數不足')
        if any(getattr(self,k)>=1 for k in ('range_width','support_tolerance','confirmation_buffer','stop_buffer','max_risk')) or self.close_location>1:raise ValueError('比例門檻不合法')
        if self.range_edge_days*2>self.range_days or self.minimum_event_age>=self.event_days:raise ValueError('整理與事件等待日數不合法')
        if not 0<self.minimum_break_fraction<self.maximum_break_fraction<1:raise ValueError('假跌破深度不合法')
        if self.event_volume_multiple<=1 or self.entry_volume_multiple<1 or self.pullback_volume_max>=1 or self.range_drift_max>=1 or self.extension_max>=1:raise ValueError('合併策略量價門檻不合法')


def evaluate(bars:list[Bar],model:str,p:NakedParameters,include_bars=False):
    if model not in NAMES and model not in ARCHIVED_NAMES:raise ValueError('未知裸 K 策略')
    if len(bars)<p.lookback:return None
    today,previous=bars[-1],bars[-2]
    liquid=bars[-p.liquidity_days:]
    if any(b.turnover is None for b in liquid) or mean(b.turnover for b in liquid)<p.minimum_turnover:return None
    if today.close<p.minimum_price or today.volume<=0:return None
    location=(today.close-today.low)/(today.high-today.low) if today.high>today.low else 0
    if today.close<=max(today.open,previous.high) or location<p.close_location:return None
    window=bars[-p.structure_days:];highs,lows=pivots(window,p.pivot_radius)
    pullback=bars[-p.pullback_days:]
    support=stop=target=None;reasons=[];extra={}
    if model==MODEL_ID:
        combined=fusion_pattern(bars,p,highs,lows,pullback)
        if combined is None:return None
        support,stop,target,reasons=(combined[k] for k in ('support','stop','target','reasons'))
        extra={k:v for k,v in combined.items() if k not in ('support','stop','target','reasons')}
    elif model=='A':
        if len(highs)<2 or len(lows)<2 or highs[-1].high<=highs[-2].high or lows[-1].low<=lows[-2].low:return None
        support=lows[-1].low
        recent_low=min(b.low for b in pullback)
        if abs(recent_low/support-1)>p.support_tolerance or today.close<support:return None
        stop=recent_low*(1-p.stop_buffer);target=highs[-1].high
        reasons=[f'確認高點 {highs[-2].high:g}→{highs[-1].high:g}、低點 {lows[-2].low:g}→{support:g}',f'最近 {p.pullback_days} 日低點回測結構支撐，距離 {abs(recent_low/support-1):.2%}']
    elif model=='B':
        base=bars[-p.range_days-p.event_days:-p.event_days];event=bars[-p.event_days:]
        upper,lower=max(b.high for b in base),min(b.low for b in base)
        if upper/lower-1>p.range_width:return None
        breaks=[i for i,b in enumerate(event[:-1]) if b.close>=upper*(1+p.confirmation_buffer)]
        if not breaks:return None
        first=breaks[0];retest=event[first+1:]
        if not retest or today.low>upper*(1+p.support_tolerance) or min(b.low for b in retest)<upper*(1-p.support_tolerance):return None
        if today.close<upper*(1+p.confirmation_buffer):return None
        support=upper;stop=min(b.low for b in retest)*(1-p.stop_buffer);target=upper+(upper-lower)
        reasons=[f'固定前 {p.range_days} 日整理 {lower:g}～{upper:g}，不以突破後資料重畫區間',f'{event[first].date} 先突破，至少隔一根後回測上緣確認；不是直接追突破']
    else:
        if len(lows)<p.support_touches or not highs:return None
        touches=lows[-p.support_touches:];support=median(b.low for b in touches)
        locations={b.date:i for i,b in enumerate(window)}
        if any(locations[b.date]-locations[a.date]<p.touch_spacing for a,b in zip(touches,touches[1:])):return None
        if any(abs(b.low/support-1)>p.support_tolerance for b in touches):return None
        if abs(today.low/support-1)>p.support_tolerance or today.close<support*(1+p.confirmation_buffer) or today.low<=previous.low:return None
        stop=min(b.low for b in pullback)*(1-p.stop_buffer);target=highs[-1].high
        reasons=[f'{p.support_touches} 個已確認低點在支撐 {support:g} 的 {p.support_tolerance:.2%} 內、彼此至少隔 {p.touch_spacing} 根', '本日低點高於前日，紅 K 收盤突破前日高點；不因下跌幅度單獨買進']
    risk=today.close-stop
    rr=(target-today.close)/risk if risk>0 else 0
    if stop<=0 or risk<=0 or risk/today.close>p.max_risk or rr<p.min_reward_risk:return None
    return {'market':today.market,'code':today.code,'name':today.name,'date':today.date,'close':today.close,
            'change_pct':round((today.close/previous.close-1)*100,2),'support':support,'stop':stop,'target':target,'reward_risk':rr,'score':1-abs(today.close/support-1),
            **extra,'model_id':model,'strategy_name':(NAMES|ARCHIVED_NAMES)[model], 'chart_price_basis':'當日已知公司行動調整，非下單成交價', 'risk_fraction':risk/today.close,
            'metrics':{'average_volume':mean(b.volume for b in liquid),'average_turnover':mean(b.turnover for b in liquid)},
            'reasons':reasons+[f'收盤突破前日高點 {previous.high:g}，收盤位置 {location:.1%}',f'此前與當日已知 {p.liquidity_days} 日官方平均成交金額 {mean(b.turnover for b in liquid):,.0f} 元'],
            'bars':[asdict(b) for b in bars[-60:]] if include_bars else []}


def screen(histories,day,model,p,events=(),include_bars=False):
    from .quality import signal_histories
    selected=[];universe=sufficient=0
    known=signal_histories(histories,day,events)
    for key in sorted(known):
        bars=known[key]
        if not bars or bars[-1].date!=day:continue
        universe+=1;sufficient+=len(bars)>=p.lookback
        signal=evaluate(bars,model,p,include_bars)
        if signal:selected.append(signal)
    selected.sort(key=lambda s:(-s['score'],s['market'],s['code']))
    return {'candidates':selected[:10],'qualified_count':len(selected),'universe_count':universe,'sufficient_history_count':sufficient}
