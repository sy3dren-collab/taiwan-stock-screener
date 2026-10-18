"""Explicit research execution assumptions; this module never places orders."""
from dataclasses import asdict, dataclass, fields
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import math


@dataclass(frozen=True)
class Execution:
    initial_capital: float = 1000000
    max_positions: int = 5
    lot_size: int = 1000
    profit_min_sessions: int = 5
    max_hold_sessions: int = 20
    fee_rate: float = 0.001425
    minimum_fee: float = 20
    sell_tax_rate: float = 0.003
    slippage_rate: float = 0.001
    max_entry_gap: float = 0.01
    max_participation: float = 0.01
    opening_limit_guard: float = 0.095

    def __post_init__(self):
        integer_names = {'max_positions', 'lot_size', 'profit_min_sessions', 'max_hold_sessions'}
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f'{field.name} 必須是有限數值')
            if field.name in integer_names and (not isinstance(value, int) or value < 1):
                raise ValueError(f'{field.name} 必須是正整數')
            if value < 0:
                raise ValueError(f'{field.name} 不可為負數')
        if self.initial_capital <= 0 or self.max_positions > 10:
            raise ValueError('本金必須大於零，持倉上限不可超過 10')
        if not 1 <= self.profit_min_sessions < self.max_hold_sessions:
            raise ValueError('停利觀察日數須小於最長持有日數')
        if any(getattr(self, key) >= 1 for key in ('fee_rate', 'sell_tax_rate', 'slippage_rate', 'max_entry_gap')):
            raise ValueError('成本與追價比例須小於 1')
        if not 0 < self.max_participation <= 1 or not 0 < self.opening_limit_guard < 0.1:
            raise ValueError('參與率須介於 0～1，開盤限制保守門檻須介於 0～10%')


def tick_price(price: float, buying: bool) -> float:
    value = Decimal(str(price))
    if not value.is_finite() or value <= 0:
        raise ValueError('價格必須是正的有限數值')
    tick = next(Decimal(t) for ceiling, t in ((10, '.01'), (50, '.05'), (100, '.1'), (500, '.5'), (1000, '1'), (math.inf, '5')) if value < Decimal(str(ceiling)))
    rounded = (value / tick).to_integral_value(rounding=ROUND_CEILING if buying else ROUND_FLOOR) * tick
    return float(max(tick, rounded))


def fill_price(open_price: float, buying: bool, execution: Execution) -> float:
    multiplier = Decimal(1) + Decimal(str(execution.slippage_rate)) * (1 if buying else -1)
    return tick_price(float(Decimal(str(open_price)) * multiplier), buying)


def commission(notional: float, execution: Execution) -> float:
    return max(execution.minimum_fee, math.floor(notional * execution.fee_rate + 1e-9))


def sell_proceeds(price: float, quantity: int, execution: Execution) -> tuple[float, float, int]:
    gross = price * quantity
    fee = commission(gross, execution)
    tax = math.floor(gross * execution.sell_tax_rate + 1e-9)
    return round(gross - fee - tax, 2), fee, tax


def entry_plan(candidate: dict, execution: Execution, parameters) -> dict:
    # Price cap after slippage must still meet the configured reward/risk threshold.
    risk_cap = (candidate['target'] + parameters.min_reward_risk * candidate['stop']) / (1 + parameters.min_reward_risk)
    max_open = tick_price(min(candidate['close'] * (1 + execution.max_entry_gap), risk_cap / (1 + execution.slippage_rate)), False)
    return {'signal_date': candidate['date'], 'entry_timing': 'next_session_open',
            'maximum_open': max_open, 'profit_min_sessions': execution.profit_min_sessions,
            'max_hold_sessions': execution.max_hold_sessions,
            'stop_rule': '收盤跌破參考停損，次一可成交交易日開盤出場；可早於一週',
            'target_rule': f'自第 {execution.profit_min_sessions} 個交易日收盤起檢查目標，次日開盤出場',
            'time_rule': f'預定第 {execution.max_hold_sessions} 個交易日開盤出場；停牌／無法成交可延後',
            'parameters': asdict(execution)}
