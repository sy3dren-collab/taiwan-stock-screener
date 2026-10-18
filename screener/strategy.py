"""Deterministic, point-in-time swing strategy. No order placement."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import math
from statistics import mean

from .data import Bar


@dataclass(frozen=True)
class Parameters:
    fast_ma: int = 20
    slow_ma: int = 60
    slope_days: int = 5
    pivot_radius: int = 2
    structure_days: int = 60
    pullback_days: int = 5
    volume_baseline_days: int = 20
    volume_ratio_max: float = 0.8
    support_distance_max: float = 0.04
    minimum_pullback: float = 0.02
    minimum_slope: float = 0.0
    atr_days: int = 14
    stop_atr_buffer: float = 0.5
    max_risk_fraction: float = 0.10
    min_reward_risk: float = 1.5
    min_average_volume: int = 300000
    max_daily_gap: float = 0.15
    target_count: int = 5
    max_candidates: int = 10

    def __post_init__(self):
        integer_names = {"fast_ma", "slow_ma", "slope_days", "pivot_radius", "structure_days", "pullback_days", "volume_baseline_days", "atr_days", "min_average_volume", "target_count", "max_candidates"}
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{f.name} 必須是有限數值")
            if f.name in integer_names and (not isinstance(value, int) or value < 1):
                raise ValueError(f"{f.name} 必須是正整數")
            if f.name not in integer_names and value < 0:
                raise ValueError(f"{f.name} 不可為負數")
        if self.fast_ma >= self.slow_ma:
            raise ValueError("fast_ma 必須小於 slow_ma")
        if not 1 <= self.target_count <= self.max_candidates <= 10:
            raise ValueError("候選數量必須滿足 1 ≤ target_count ≤ max_candidates ≤ 10")
        if not 0 < self.volume_ratio_max <= 1 or not 0 < self.max_risk_fraction < 1:
            raise ValueError("量縮比例必須介於 0～1，風險比例必須介於 0～1（不含端點）")
        if self.min_reward_risk <= 0 or self.support_distance_max <= 0 or self.max_daily_gap <= 0:
            raise ValueError("風報比、支撐距離及價格跳空上限必須大於零")
        if self.structure_days < self.pivot_radius * 2 + 3:
            raise ValueError("structure_days 不足以確認波段轉折")

    @property
    def required_bars(self) -> int:
        return max(self.slow_ma + self.slope_days, self.structure_days,
                   self.pullback_days + self.volume_baseline_days + 1, self.atr_days + 1)


def pivots(bars: list[Bar], radius: int) -> tuple[list[Bar], list[Bar]]:
    highs, lows = [], []
    # A pivot is confirmed only after radius subsequent trading bars.
    for i in range(radius, len(bars) - radius):
        neighbors = bars[i-radius:i] + bars[i+1:i+radius+1]
        if all(bars[i].high > b.high for b in neighbors):
            highs.append(bars[i])
        if all(bars[i].low < b.low for b in neighbors):
            lows.append(bars[i])
    return highs, lows


def evaluate(bars: list[Bar], p: Parameters) -> dict | None:
    if len(bars) < p.required_bars:
        return None
    today, yesterday = bars[-1], bars[-2]
    closes = [b.close for b in bars]
    fast = mean(closes[-p.fast_ma:])
    slow = mean(closes[-p.slow_ma:])
    past_fast = mean(closes[-p.fast_ma-p.slope_days:-p.slope_days])
    slope = fast / past_fast - 1
    if not (today.close > fast > slow and slope > p.minimum_slope):
        return None
    # Unadjusted official prices: conservatively omit unusual discontinuities.
    recent = bars[-p.structure_days:]
    if any(abs(b.close / a.close - 1) > p.max_daily_gap for a, b in zip(recent, recent[1:])):
        return None
    highs, lows = pivots(recent, p.pivot_radius)
    if len(highs) < 2 or len(lows) < 2 or not (highs[-1].high > highs[-2].high and lows[-1].low > lows[-2].low):
        return None
    pullback = bars[-p.pullback_days-1:-1]
    baseline = bars[-p.pullback_days-p.volume_baseline_days-1:-p.pullback_days-1]
    baseline_volume = mean(b.volume for b in baseline)
    if baseline_volume <= 0:
        return None
    volume_ratio = mean(b.volume for b in pullback) / baseline_volume
    avg_volume = mean(b.volume for b in bars[-p.volume_baseline_days:])
    if volume_ratio > p.volume_ratio_max or avg_volume < p.min_average_volume:
        return None
    peak = max(b.high for b in bars[-p.fast_ma-1:-1])
    pullback_low = min(b.low for b in pullback)
    depth = 1 - pullback_low / peak
    if depth < p.minimum_pullback:
        return None
    supports = [("20 日均線" if p.fast_ma == 20 else f"{p.fast_ma} 日均線", fast), ("最近確認波段低點", lows[-1].low)]
    supports = [(label, value) for label, value in supports if value <= today.close and abs(pullback_low / value - 1) <= p.support_distance_max and today.close / value - 1 <= p.support_distance_max]
    if not supports:
        return None
    support_label, support = min(supports, key=lambda s: abs(today.close - s[1]))
    # Closing above yesterday's high AND a positive candle confirm resumption.
    if not (today.close > yesterday.high and today.close > today.open and today.close > yesterday.close):
        return None
    true_ranges = [max(b.high-b.low, abs(b.high-a.close), abs(b.low-a.close)) for a, b in zip(bars, bars[1:])]
    atr = mean(true_ranges[-p.atr_days:])
    stop = min(support, pullback_low) - p.stop_atr_buffer * atr
    target = highs[-1].high
    risk = today.close - stop
    reward_risk = (target - today.close) / risk if risk > 0 else 0
    if stop <= 0 or risk / today.close > p.max_risk_fraction or reward_risk < p.min_reward_risk:
        return None
    distance = today.close / support - 1
    score = round(40 * (1 - distance / p.support_distance_max) + 30 * (1 - volume_ratio) + 20 * min(reward_risk / 3, 1) + 10 * min(slope / 0.05, 1), 4)
    return {
        "market": today.market, "code": today.code, "name": today.name, "date": today.date,
        "close": today.close, "change_pct": round((today.close/yesterday.close-1)*100, 2),
        "support": round(support, 3), "stop": round(stop, 3), "target": round(target, 3),
        "reward_risk": round(reward_risk, 2), "score": score,
        "metrics": {"fast_ma": round(fast, 3), "slow_ma": round(slow, 3), "ma_slope": round(slope, 5),
                    "volume_ratio": round(volume_ratio, 3), "support_distance": round(distance, 5),
                    "atr": round(atr, 3), "pullback_depth": round(depth, 4), "average_volume": round(avg_volume)},
        "reasons": [f"收盤 {today.close:g} > MA{p.fast_ma} {fast:.2f} > MA{p.slow_ma} {slow:.2f}，短均線 {p.slope_days} 日升幅 {slope:.2%}",
                    f"確認波段高點 {highs[-2].high:g} → {highs[-1].high:g}；低點 {lows[-2].low:g} → {lows[-1].low:g}",
                    f"接近{support_label} {support:.2f}，收盤距離 {distance:.2%}",
                    f"前 {p.pullback_days} 日均量／此前 {p.volume_baseline_days} 日均量 = {volume_ratio:.2f}",
                    f"紅 K 收盤突破前日高點 {yesterday.high:g}；回檔深度 {depth:.2%}"],
        "bars": [asdict(b) for b in bars[-90:]],
    }


def screen(histories: dict[tuple[str, str], list[Bar]], as_of: str, p: Parameters) -> dict:
    """Future backtests can call this with any as_of; future bars are discarded."""
    candidates = []
    eligible = 0
    sufficient_history = 0
    for key in sorted(histories):
        bars = sorted((b for b in histories[key] if b.date <= as_of), key=lambda b: b.date)
        if not bars or bars[-1].date != as_of:
            continue  # No stale quotes from suspended securities.
        eligible += 1
        if len(bars) >= p.required_bars:
            sufficient_history += 1
        candidate = evaluate(bars, p)
        if candidate:
            candidates.append(candidate)
    candidates.sort(key=lambda c: (-c["score"], c["market"], c["code"]))
    selected = candidates[:p.max_candidates]
    return {"candidates": selected, "universe_count": eligible, "sufficient_history_count": sufficient_history,
            "qualified_count": len(candidates), "shortfall": len(selected) < p.target_count,
            "parameters": asdict(p)}
