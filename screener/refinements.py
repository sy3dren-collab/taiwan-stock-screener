"""One predeclared candidate per baseline, not a parameter search or recommendation."""
from dataclasses import asdict, dataclass, fields, replace
import math
from statistics import mean

from .models import ModelSettings

WEAKNESSES = {
 'user_range_reclaim': ['收復下緣可能只是弱勢反彈，紅 K 與大量仍不保證買盤延續。', '區間上緣可能較遠，固定 20 日內未必到達；少數型態樣本不足。'],
 'trend_pullback': ['確認轉折與均線有延遲，可能在趨勢末段才入選。', '前日高點突破未要求當日量能，弱反彈也可能觸發。'],
 'volume_breakout': ['原排序獎勵突破幅度，可能優先追進過度延伸的股票。', '取 MA 與 ATR 較高值的停損可能過緊，固定 2R 也不是已知壓力價。'],
 'rsi_recovery': ['簡單平均 RSI 可能因舊價格移出視窗而跳過門檻。', '單次穿越門檻未確認量能，小幅反彈可能被交易成本抵銷。'],
}
CHANGES = {
 'user_range_reclaim': '保留長整理與收復／突破量至少 1.5 倍；另須收盤突破前日高點，並位於當日振幅上方 30%。',
 'trend_pullback': '保留原五項條件；轉強日量至少等於此前 20 日均量，收盤位於當日振幅上方 30%。',
 'volume_breakout': '突破距離不超過 1ATR，距 MA20 不超過 8%；收盤位於振幅上方 30%，停損改為收盤減 2ATR，優先靠近突破點者。',
 'rsi_recovery': '改用 Wilder 平滑 RSI14 穿越中線 50；保留均線與突破前日高點，另要求當日量不低於此前 20 日均量及收盤位於振幅上方 30%。',
}

@dataclass(frozen=True)
class Refinements:
    max_signal_risk: float = .06
    min_average_turnover: float = 20000000
    max_atr_fraction: float = .06
    minimum_close_location: float = .7
    confirmation_volume_multiple: float = 1.0
    rsi_recovery_level: float = 50.0
    breakout_extension_atr: float = 1.0
    breakout_ma_distance: float = .08
    risk_budget_fraction: float = .01
    breakeven_trigger_r: float = 1.0
    failure_sessions: int = 5
    failure_min_r: float = .5

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'{field.name} 必須是正的有限數值')
        if self.rsi_recovery_level >= 100:
            raise ValueError('改良 RSI 門檻須介於 0～100')
        if not isinstance(self.failure_sessions, int):
            raise ValueError('failure_sessions 必須是正整數')
        if any(getattr(self, name) >= 1 for name in ('max_signal_risk', 'max_atr_fraction', 'breakout_ma_distance', 'risk_budget_fraction')) or self.minimum_close_location > 1:
            raise ValueError('風險、振幅、距離比例須小於 1，收盤位置不可超過 1')


def refined_screen(histories, day, p, model, m=None, settings=None):
    m, settings = m or ModelSettings(), settings or Refinements()
    # Preserve the full qualified set before applying extra gates, then re-rank.
    # screen_model returns only the top ten, so evaluate one security at a time.
    candidates, universe, sufficient = [], 0, 0
    from .models import alternative, required_bars
    from .strategy import evaluate
    refined_m = replace(m, rsi_wilder=True, rsi_recovery_level=settings.rsi_recovery_level) if model == 'rsi_recovery' else m
    for key in sorted(histories):
        bars = sorted((b for b in histories[key] if b.date <= day), key=lambda b:b.date)
        if not bars or bars[-1].date != day:
            continue
        universe += 1
        sufficient += len(bars) >= required_bars(p, refined_m, model)
        signal = evaluate(bars, p, include_bars=False) if model == 'trend_pullback' else alternative(bars, p, model, refined_m, include_bars=False)
        if not signal:
            continue
        today, previous = bars[-1], bars[-2]
        baseline = mean(b.volume for b in bars[-p.volume_baseline_days-1:-1])
        turnover = mean(b.close*b.volume for b in bars[-p.volume_baseline_days:])
        atr = mean(max(b.high-b.low, abs(b.high-a.close), abs(b.low-a.close)) for a,b in zip(bars[-p.atr_days-1:-1], bars[-p.atr_days:]))
        location = (today.close-today.low)/(today.high-today.low) if today.high>today.low else 0
        if turnover < settings.min_average_turnover or atr/today.close > settings.max_atr_fraction or location < settings.minimum_close_location:
            continue
        if model == 'user_range_reclaim' and today.close <= previous.high:
            continue
        if model in ('trend_pullback','rsi_recovery') and today.volume < baseline*settings.confirmation_volume_multiple:
            continue
        if model == 'volume_breakout':
            peak = max(b.high for b in bars[-m.breakout_days-1:-1])
            fast = mean(b.close for b in bars[-p.fast_ma:])
            extension = (today.close-peak)/atr if atr else math.inf
            if extension > settings.breakout_extension_atr or today.close/fast-1 > settings.breakout_ma_distance:
                continue
            stop = today.close-m.breakout_stop_atr*atr
            signal.update(stop=round(stop,3), target=round(today.close+m.breakout_target_r*(today.close-stop),3),
                          score=round(100*(1-extension/settings.breakout_extension_atr),4))
        risk = today.close-signal['stop']
        rr = (signal['target']-today.close)/risk if risk>0 else 0
        if risk <= 0 or signal['stop'] <= 0 or risk/today.close>min(p.max_risk_fraction,settings.max_signal_risk) or rr<p.min_reward_risk:
            continue
        signal.update(reward_risk=round(rr,4), refinement='fixed_v1')
        signal['reasons'].append(f'改良候選：收盤位置 {location:.0%}，日均成交金額約 {turnover:,.0f} 元；訊號風險距離 {risk/today.close:.2%}')
        candidates.append(signal)
    candidates.sort(key=lambda c:(-c['score'],c['market'],c['code']))
    return {'candidates':candidates[:p.max_candidates], 'qualified_count':len(candidates),
            'universe_count':universe,'sufficient_history_count':sufficient,'parameters':asdict(p)}
