"""One staged swing setup combining consolidation, rising structure and volume confirmation."""
from statistics import mean

MODEL_ID='F'
MODEL_NAME='整理收復・趨勢回測・放量轉強'


def pattern(bars,p,highs,lows,pullback):
    today=bars[-1]
    base=bars[-p.range_days-p.event_days:-p.event_days]
    upper,lower=max(b.high for b in base),min(b.low for b in base)
    drift=abs(mean(b.close for b in base[-p.range_edge_days:])/mean(b.close for b in base[:p.range_edge_days])-1)
    if upper/lower-1>p.range_width or drift>p.range_drift_max:return None
    if len(highs)<2 or len(lows)<2 or highs[-1].high<=highs[-2].high or lows[-1].low<=lows[-2].low:return None
    support=lows[-1].low;recent_low=min(b.low for b in pullback)
    if abs(recent_low/support-1)>p.support_tolerance or not support<=today.close<=support*(1+p.extension_max):return None
    before=bars[-p.pullback_days-p.liquidity_days-1:-p.pullback_days-1]
    retrace=bars[-p.pullback_days-1:-1]
    before_volume=mean(b.volume for b in before)
    entry_base=mean(b.volume for b in bars[-p.liquidity_days-1:-1])
    if before_volume<=0 or entry_base<=0:return None
    contraction=mean(b.volume for b in retrace)/before_volume
    entry_ratio=today.volume/entry_base
    if contraction>p.pullback_volume_max or entry_ratio<p.entry_volume_multiple:return None
    first=len(bars)-p.event_days
    # Most recent qualifying event is fixed before examining the subsequent retest.
    events=[]
    for i in range(first,len(bars)-p.minimum_event_age):
        event=bars[i];previous=bars[i-1];history=bars[i-p.liquidity_days:i]
        if len(history)!=p.liquidity_days:continue
        event_base=mean(b.volume for b in history)
        if event_base<=0:continue
        ratio=event.volume/event_base
        if event.close<=event.open or ratio<p.event_volume_multiple:continue
        depth=1-event.low/lower
        reclaim=p.minimum_break_fraction<=depth<=p.maximum_break_fraction and event.close>=lower*(1+p.confirmation_buffer)
        breakout=event.close>=upper*(1+p.confirmation_buffer) and previous.close<upper*(1+p.confirmation_buffer)
        if reclaim or breakout:events.append((i,event,ratio,'大量假跌破收復' if reclaim else '大量突破整理上緣',lower if reclaim else upper))
    if not events:return None
    i,event,event_ratio,variant,level=events[-1]
    if lows[-1].date<=event.date:return None
    after=bars[i+1:]
    if min(b.close for b in after)<level*(1-p.support_tolerance):return None
    if variant=='大量突破整理上緣' and recent_low<upper*(1-p.support_tolerance):return None
    target=upper if variant=='大量假跌破收復' else upper+(upper-lower)
    stop=min(support,recent_low)*(1-p.stop_buffer)
    return {'support':support,'stop':stop,'target':target,'setup_date':event.date,'variant':variant,
            'fusion_metrics':{'setup_volume_ratio':event_ratio,'entry_volume_ratio':entry_ratio,'pullback_volume_ratio':contraction,'range_upper':upper,'range_lower':lower},
            'reasons':[f'固定前 {p.range_days} 根整理 {lower:g}～{upper:g}，首尾均價漂移 {drift:.2%}',
                       f'{event.date} {variant}，事件當日量為此前 {p.liquidity_days} 日均量 {event_ratio:.2f} 倍',
                       f'已確認高點 {highs[-2].high:g}→{highs[-1].high:g}、低點 {lows[-2].low:g}→{support:g}，最新較高低點在事件之後',
                       f'回檔 {p.pullback_days} 日量比 {contraction:.2f}，低點回測支撐；本日再轉強量比 {entry_ratio:.2f}',
                       f'收盤距結構支撐 {today.close/support-1:.2%}，上限 {p.extension_max:.2%}；目標取已知區間價位']}
