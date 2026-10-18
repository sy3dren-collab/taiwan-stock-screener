"""Prespecified models; the user's range strategy is kept independent."""
from dataclasses import asdict, dataclass, fields
import math
from statistics import mean

from .data import Bar
from .strategy import Parameters, pivots, screen

MODELS = {
    'user_range_reclaim': {'name': '你的策略：整理區間＋大量收復', 'description': '長時間整理後，假跌破收復區間或量化近似頭肩底突破頸線；收復／突破當天必須放量。'},
    'trend_pullback': {'name': '原策略：趨勢回檔再轉強', 'description': '均線多頭、高低點抬高、近支撐量縮，紅 K 收盤突破前日高點。'},
    'volume_breakout': {'name': '比較策略：帶量突破', 'description': '均線多頭且上升，收盤帶量突破前高；以 ATR 設停損、固定 R 倍設模型目標。'},
    'rsi_recovery': {'name': '比較策略：趨勢中的 RSI 回升', 'description': '均線多頭且上升，簡單平均 RSI 向上穿越門檻，紅 K 突破前日高點，且接近短均線。'},
}


@dataclass(frozen=True)
class ModelSettings:
    breakout_days: int = 20
    breakout_volume_multiple: float = 1.5
    breakout_stop_atr: float = 2.0
    breakout_target_r: float = 2.0
    rsi_days: int = 14
    rsi_recovery_level: float = 40
    rsi_stop_atr: float = 0.5
    range_days: int = 60
    range_edge_days: int = 10
    recovery_days: int = 10
    range_width_max: float = 0.25
    range_drift_max: float = 0.08
    minimum_break_fraction: float = 0.005
    maximum_break_fraction: float = 0.08
    reclaim_buffer: float = 0.005
    event_volume_multiple: float = 1.5
    pattern_days: int = 60
    pattern_pivot_radius: int = 2
    head_depth_min: float = 0.03
    shoulder_tolerance: float = 0.05
    shoulder_min_spacing: int = 5
    shoulder_max_spacing: int = 25
    shoulder_time_ratio_max: float = 2.0
    neckline_difference_max: float = 0.10

    def __post_init__(self):
        integers = {'breakout_days', 'rsi_days', 'range_days', 'range_edge_days', 'recovery_days',
                    'pattern_days', 'pattern_pivot_radius', 'shoulder_min_spacing', 'shoulder_max_spacing'}
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'{field.name} 必須是正的有限數值')
            if field.name in integers and not isinstance(value, int):
                raise ValueError(f'{field.name} 必須是正整數')
        if self.event_volume_multiple <= 1 or self.breakout_volume_multiple < 1:
            raise ValueError('放量倍數必須高於 1；突破量比不可低於 1')
        if any(getattr(self, key) >= 1 for key in ('range_width_max', 'range_drift_max', 'reclaim_buffer', 'head_depth_min', 'shoulder_tolerance', 'neckline_difference_max')):
            raise ValueError('區間與型態比例必須小於 1')
        if not 0 < self.rsi_recovery_level < 100:
            raise ValueError('RSI 門檻須介於 0～100')
        if self.range_edge_days*2 > self.range_days or self.range_days < 10:
            raise ValueError('整理區間不足以衡量首尾均價漂移')
        if self.minimum_break_fraction >= self.maximum_break_fraction or self.maximum_break_fraction >= 1:
            raise ValueError('假跌破深度上下限不合法')
        if self.shoulder_min_spacing > self.shoulder_max_spacing or self.shoulder_time_ratio_max < 1:
            raise ValueError('肩部間距條件不合法')
        if self.pattern_days < self.pattern_pivot_radius*2+3:
            raise ValueError('型態觀察日數不足')


def required_bars(p: Parameters, m: ModelSettings, model: str) -> int:
    if model == 'user_range_reclaim':
        return max(p.required_bars, m.range_days+m.recovery_days, m.pattern_days+1)
    return max(p.required_bars, m.breakout_days+1, m.rsi_days+2)


def rsi(closes: list[float], days: int = 14) -> float:
    changes = [b-a for a, b in zip(closes[-days-1:], closes[-days:])]
    gain, loss = mean(max(x, 0) for x in changes), mean(max(-x, 0) for x in changes)
    return 100 if loss == 0 and gain > 0 else 50 if loss == gain == 0 else 100-100/(1+gain/loss)


def consolidation(bars: list[Bar], m: ModelSettings) -> tuple | None:
    upper, lower = max(b.high for b in bars), min(b.low for b in bars)
    width = upper/lower-1
    drift = abs(mean(b.close for b in bars[-m.range_edge_days:])/mean(b.close for b in bars[:m.range_edge_days])-1)
    return (upper, lower, width, drift) if width <= m.range_width_max and drift <= m.range_drift_max else None


def user_pattern(bars: list[Bar], p: Parameters, m: ModelSettings, atr: float) -> dict | None:
    today, yesterday = bars[-1], bars[-2]
    base_volume = mean(b.volume for b in bars[-p.volume_baseline_days-1:-1])
    volume_ratio = today.volume/base_volume if base_volume else 0
    # Mandatory in BOTH of the user's variants, never an optional score bonus.
    if volume_ratio < m.event_volume_multiple or today.close <= today.open:
        return None
    base = consolidation(bars[-m.range_days-m.recovery_days:-m.recovery_days], m)
    if base:
        upper, lower, width, drift = base
        event = bars[-m.recovery_days:]
        low = min(b.low for b in event)
        depth = 1-low/lower
        fresh_reclaim = yesterday.close < lower*(1+m.reclaim_buffer) or today.low < lower*(1-m.minimum_break_fraction)
        if m.minimum_break_fraction <= depth <= m.maximum_break_fraction and today.close >= lower*(1+m.reclaim_buffer) and fresh_reclaim:
            return {'variant': '假跌破後大量收復', 'support': lower,
                    'stop': low-p.stop_atr_buffer*atr, 'target': upper,
                    'score': min(volume_ratio/3, 1)*50+min(depth/m.maximum_break_fraction, 1)*50,
                    'reasons': [f'前 {m.range_days} 日整理區間 {lower:.2f}～{upper:.2f}，振幅 {width:.2%}、首尾均價漂移 {drift:.2%}',
                                f'最近 {m.recovery_days} 日曾跌破下緣 {depth:.2%}，本日收盤重新站回區間',
                                f'收復當日成交量為此前 {p.volume_baseline_days} 日均量的 {volume_ratio:.2f} 倍（至少 {m.event_volume_multiple:g} 倍）']}
    base = consolidation(bars[-m.range_days-1:-1], m)
    if not base:
        return None
    window = bars[-m.pattern_days:]
    _, lows = pivots(window, m.pattern_pivot_radius)
    if len(lows) < 3:
        return None
    left, head, right = lows[-3:]
    locations = {b.date: i for i, b in enumerate(window)}
    a, h, b = (locations[x.date] for x in (left, head, right))
    gaps = (h-a, b-h)
    if not (m.shoulder_min_spacing <= min(gaps) <= max(gaps) <= m.shoulder_max_spacing and max(gaps)/min(gaps) <= m.shoulder_time_ratio_max):
        return None
    if head.low > min(left.low, right.low)*(1-m.head_depth_min) or abs(left.low/right.low-1) > m.shoulder_tolerance:
        return None
    peak1 = max(range(a+1, h), key=lambda i: window[i].high)
    peak2 = max(range(h+1, b), key=lambda i: window[i].high)
    if abs(window[peak2].high/window[peak1].high-1) > m.neckline_difference_max:
        return None
    def neckline(i):
        return window[peak1].high+(window[peak2].high-window[peak1].high)*(i-peak1)/(peak2-peak1)
    neck = neckline(len(window)-1)
    if not (today.close >= neck*(1+m.reclaim_buffer) and yesterday.close < neckline(len(window)-2)*(1+m.reclaim_buffer)):
        return None
    return {'variant': '量化近似頭肩底頸線突破', 'support': neck,
            'stop': right.low-p.stop_atr_buffer*atr, 'target': neck+neckline(h)-head.low,
            'score': min(volume_ratio/3, 1)*50+50*(1-abs(left.low/right.low-1)/m.shoulder_tolerance),
            'reasons': [f'前 {m.range_days} 日符合整理振幅與漂移上限',
                        f'三個已確認低點：左肩 {left.low:g}、頭部 {head.low:g}、右肩 {right.low:g}；非人工確認形態',
                        f'收盤突破估算頸線 {neck:.2f}，成交量為此前 {p.volume_baseline_days} 日均量 {volume_ratio:.2f} 倍',
                        '目標為頸線加頭部深度的型態等幅估算，非已發生行情']}


def alternative(bars: list[Bar], p: Parameters, model: str, m: ModelSettings | None = None) -> dict | None:
    m = m or ModelSettings()
    if len(bars) < required_bars(p, m, model):
        return None
    today, yesterday = bars[-1], bars[-2]
    closes = [b.close for b in bars]
    average_volume = mean(b.volume for b in bars[-p.volume_baseline_days:])
    if average_volume < p.min_average_volume:
        return None
    recent = bars[-p.structure_days:]
    if any(abs(b.close/a.close-1) > p.max_daily_gap for a, b in zip(recent, recent[1:])):
        return None
    atr = mean(max(b.high-b.low, abs(b.high-a.close), abs(b.low-a.close)) for a, b in zip(bars[-p.atr_days-1:-1], bars[-p.atr_days:]))
    if model == 'user_range_reclaim':
        pattern = user_pattern(bars, p, m, atr)
        if pattern is None:
            return None
    else:
        fast, slow = mean(closes[-p.fast_ma:]), mean(closes[-p.slow_ma:])
        past_fast = mean(closes[-p.fast_ma-p.slope_days:-p.slope_days])
        if not (today.close > fast > slow and fast/past_fast-1 > p.minimum_slope):
            return None
        peak = max(b.high for b in bars[-m.breakout_days-1:-1])
        if model == 'volume_breakout':
            base_volume = mean(b.volume for b in bars[-m.breakout_days-1:-1])
            ratio = today.volume/base_volume if base_volume else 0
            if not (today.close > peak and today.close > today.open and ratio >= m.breakout_volume_multiple):
                return None
            stop = max(fast, today.close-m.breakout_stop_atr*atr)
            pattern = {'variant': '帶量突破', 'support': peak, 'stop': stop,
                       'target': today.close+m.breakout_target_r*(today.close-stop),
                       'score': min(ratio/3, 1)*50+min((today.close/peak-1)/.05, 1)*50,
                       'reasons': [f'收盤突破前 {m.breakout_days} 日高點 {peak:.2f}', f'量比 {ratio:.2f} ≥ {m.breakout_volume_multiple:g}',
                                   f'停損採 MA 或 {m.breakout_stop_atr:g} ATR；目標為模型 {m.breakout_target_r:g}R']}
        elif model == 'rsi_recovery':
            previous, current = rsi(closes[:-1], m.rsi_days), rsi(closes, m.rsi_days)
            if not (previous <= m.rsi_recovery_level < current and today.close > yesterday.high and today.close > today.open and today.close/fast-1 <= p.support_distance_max):
                return None
            pattern = {'variant': 'RSI 回升', 'support': fast,
                       'stop': min(b.low for b in bars[-p.pullback_days-1:-1])-m.rsi_stop_atr*atr,
                       'target': peak, 'score': 50+min(current-m.rsi_recovery_level, 30)/30*50,
                       'reasons': [f'簡單平均 RSI{m.rsi_days} {previous:.2f} → {current:.2f}，向上穿越 {m.rsi_recovery_level:g}',
                                   '紅 K 收盤突破前日高點，且接近短均線', f'參考目標為前 {m.breakout_days} 日高點 {peak:.2f}']}
        else:
            raise ValueError('未知策略')
    risk = today.close-pattern['stop']
    rr = (pattern['target']-today.close)/risk if risk > 0 else 0
    if pattern['stop'] <= 0 or risk <= 0 or risk/today.close > p.max_risk_fraction or rr < p.min_reward_risk:
        return None
    return {'market': today.market, 'code': today.code, 'name': today.name, 'date': today.date,
            'close': today.close, 'change_pct': round((today.close/yesterday.close-1)*100, 2),
            'stop': round(pattern['stop'], 3), 'target': round(pattern['target'], 3), 'support': round(pattern['support'], 3),
            'reward_risk': round(rr, 4), 'score': round(pattern['score'], 4), 'reasons': pattern['reasons'],
            'variant': pattern['variant'], 'metrics': {'average_volume': average_volume}, 'model_id': model,
            'bars': [asdict(b) for b in bars[-90:]]}


def screen_model(histories: dict, as_of: str, p: Parameters, model: str, m: ModelSettings | None = None) -> dict:
    m = m or ModelSettings()
    if model == 'trend_pullback':
        return screen(histories, as_of, p)
    if model not in MODELS:
        raise ValueError('未知策略')
    candidates, universe, sufficient = [], 0, 0
    for key in sorted(histories):
        bars = sorted((b for b in histories[key] if b.date <= as_of), key=lambda b: b.date)
        if not bars or bars[-1].date != as_of:
            continue
        universe += 1
        sufficient += len(bars) >= required_bars(p, m, model)
        signal = alternative(bars, p, model, m)
        if signal:
            candidates.append(signal)
    candidates.sort(key=lambda c: (-c['score'], c['market'], c['code']))
    selected = candidates[:p.max_candidates]
    return {'candidates': selected, 'qualified_count': len(candidates), 'parameters': asdict(p),
            'universe_count': universe, 'sufficient_history_count': sufficient, 'shortfall': len(selected) < p.target_count}
