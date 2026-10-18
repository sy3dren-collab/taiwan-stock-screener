"""Preliminary, unadjusted-price research simulation; never a trading service."""
from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime
import json
import logging
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

from .data import Bar, DataError, Store
from .execution import Execution, commission, fill_price, sell_proceeds
from .models import MODELS, ModelSettings, required_bars, screen_model
from .strategy import Parameters


@dataclass
class Position:
    market: str
    code: str
    name: str
    signal_date: str
    entry_date: str
    entry_index: int
    entry_price: float
    quantity: int
    entry_fee: float
    stop: float
    target: float
    cost: float
    signal_variant: str = ''


def simulate(histories: dict, parameters: Parameters, execution: Execution,
             model: str = 'trend_pullback', start: str | None = None,
             end: str | None = None, signal_function=None, model_settings: ModelSettings | None = None) -> dict:
    """Entries use only the preceding close. Closing triggers execute next open.

    signal_function is an injectable point-in-time signal boundary for testing.
    No current day's closing price participates in an opening decision.
    """
    model_settings = model_settings or ModelSettings()
    required = required_bars(parameters, model_settings, model)
    if model not in MODELS:
        raise ValueError('未知策略')
    histories = {key: sorted((b for b in bars if end is None or b.date <= end), key=lambda b: b.date)
                 for key, bars in histories.items()}
    dates = sorted({bar.date for bars in histories.values() for bar in bars})
    if len(dates) <= required:
        raise DataError(f'至少需要 {required + 1} 個市場交易日（含暖機）才能回測')
    first_index = max(required-1, bisect_left(dates, start) if start else 0)
    active_dates = dates[first_index:]
    if len(active_dates) < 2:
        raise DataError('扣除均線暖機後，回測期間不足兩個交易日')
    indices = {key: [b.date for b in bars] for key, bars in histories.items()}
    by_day: dict[str, dict] = {}
    for key, bars in histories.items():
        if len(set(indices[key])) != len(bars):
            raise DataError('歷史資料出現重複交易日')
        for bar in bars:
            by_day.setdefault(bar.date, {})[key] = bar
    cash = float(execution.initial_capital)
    positions: dict[tuple[str, str], Position] = {}
    exits: dict[tuple[str, str], str] = {}
    orders: list[dict] = []
    closed = []
    rejected = Counter()
    deferred = Counter()
    discontinuities = set()
    last_close = {}
    last_quote = {}
    for key, bars in histories.items():
        previous = [b for b in bars if b.date < active_dates[0]]
        if previous:
            last_close[key], last_quote[key] = previous[-1].close, previous[-1].date
    curve = [{'date': dates[first_index-1], 'equity': cash, 'cash': cash, 'positions': 0}]
    signal_count = 0
    for day_index, day in enumerate(active_dates):
        quotes = by_day[day]
        # 1. Previously scheduled exits execute at today's open, not yesterday's close.
        for key in list(exits):
            position = positions[key]
            bar = quotes.get(key)
            if bar is None or bar.volume < position.quantity:
                deferred['無行情或成交量不足'] += 1
                continue
            if bar.open <= last_close[key]*(1-execution.opening_limit_guard):
                deferred['開盤近跌停，保守假設無法賣出'] += 1
                continue
            price = fill_price(bar.open, False, execution)
            proceeds, fee, tax = sell_proceeds(price, position.quantity, execution)
            cash = round(cash+proceeds, 2)
            pnl = round(proceeds-position.cost, 2)
            closed.append({**asdict(position), 'exit_date': day, 'exit_price': price,
                           'exit_fee': fee, 'sell_tax': tax, 'exit_reason': exits.pop(key),
                           'holding_sessions': day_index-position.entry_index+1,
                           'calendar_days': (date.fromisoformat(day)-date.fromisoformat(position.entry_date)).days,
                           'net_pnl': pnl, 'net_return': round(pnl/position.cost, 8)})
            del positions[key]
        # 2. Only signals generated on the immediately preceding market session may enter.
        for signal in orders:
            key = signal['market'], signal['code']
            if key in positions:
                rejected['已持有同一股票'] += 1
                continue
            if len(positions) >= execution.max_positions:
                rejected['持倉已滿'] += 1
                continue
            bar = quotes.get(key)
            if bar is None or bar.volume <= 0:
                rejected['次日無可成交行情'] += 1
                continue
            if bar.open >= signal['close']*(1+execution.opening_limit_guard):
                rejected['開盤近漲停，保守不追單'] += 1
                continue
            if bar.open > signal['close']*(1+execution.max_entry_gap):
                rejected['超過追價上限'] += 1
                continue
            price = fill_price(bar.open, True, execution)
            risk = price-signal['stop']
            rr = (signal['target']-price)/risk if risk > 0 else 0
            if risk <= 0 or risk/price > parameters.max_risk_fraction or rr < parameters.min_reward_risk:
                rejected['次日開盤後風險條件不合格'] += 1
                continue
            budget = min(cash, execution.initial_capital/execution.max_positions)
            average_volume = signal['metrics']['average_volume']
            capacity = int(average_volume*execution.max_participation/execution.lot_size)*execution.lot_size
            quantity = min(int(budget/price/execution.lot_size)*execution.lot_size, capacity)
            while quantity > 0 and price*quantity+commission(price*quantity, execution) > budget:
                quantity -= execution.lot_size
            if quantity <= 0 or bar.volume < quantity:
                rejected['整張資金或流動性不足'] += 1
                continue
            fee = commission(price*quantity, execution)
            cost = round(price*quantity+fee, 2)
            cash = round(cash-cost, 2)
            positions[key] = Position(*key, signal['name'], signal['date'], day, day_index,
                                      price, quantity, fee, signal['stop'], signal['target'], cost, signal.get('variant', '趨勢回檔再轉強'))
        # 3. Closing data now becomes available; use it only for tomorrow's orders.
        for key, bar in quotes.items():
            if key in positions and key in last_close and abs(bar.close/last_close[key]-1) > parameters.max_daily_gap:
                discontinuities.add(f'{key[0]}:{key[1]}:{day}')
            last_close[key], last_quote[key] = bar.close, day
        for key, position in positions.items():
            holding = day_index-position.entry_index+1
            bar = quotes.get(key)
            if key in exits:
                continue
            if bar and bar.close <= position.stop:
                exits[key] = '收盤停損'
            elif bar and holding >= execution.profit_min_sessions and bar.close >= position.target:
                exits[key] = '收盤達目標'
            elif holding >= execution.max_hold_sessions-1:
                exits[key] = '持有時間到期'
        value = cash
        for key, position in positions.items():
            marked = fill_price(last_close[key], False, execution)
            value += sell_proceeds(marked, position.quantity, execution)[0]
        curve.append({'date': day, 'equity': round(value, 2), 'cash': cash, 'positions': len(positions)})
        # Truncate histories at this date even when a caller supplied future bars.
        known = {key: bars[:bisect_right(indices[key], day)] for key, bars in histories.items()}
        result = signal_function(known, day, parameters) if signal_function else screen_model(known, day, parameters, model, model_settings)
        signals = result['candidates']
        if any(s['date'] != day for s in signals):
            raise DataError('訊號日期與回測日不一致')
        signal_count += len(signals)
        eligible_orders = [s for s in signals if (s['market'], s['code']) not in positions]
        slots = max(0, execution.max_positions-len(positions))
        rejected['前日持倉預留限制'] += max(0, len(eligible_orders)-slots)
        # Reserve slots at the prior close. Never substitute a lower-ranked stock
        # after discovering next day's volume or an unfilled opening order.
        orders = eligible_orders[:slots]
    peak = execution.initial_capital
    max_drawdown = 0
    for point in curve:
        peak = max(peak, point['equity'])
        max_drawdown = max(max_drawdown, 1-point['equity']/peak)
    winners = [t for t in closed if t['net_pnl'] > 0]
    losses = [t for t in closed if t['net_pnl'] < 0]
    gross_profit = sum(t['net_pnl'] for t in winners)
    gross_loss = -sum(t['net_pnl'] for t in losses)
    open_positions = [{**asdict(p), 'last_quote_date': last_quote[k], 'last_close': last_close[k],
                       'holding_sessions': len(active_dates)-p.entry_index,
                       'pending_exit': exits.get(k)} for k, p in positions.items()]
    warnings = ['原始未還原權息價格：未計入股息、除權／減資調整，結果不能視為完整投資報酬。',
                '日線開盤價與滑價僅為成交模型，未模擬完整漲跌停參考價、開盤委託佇列及部分成交。',
                '收盤觸發後次日開盤執行，跳空可能使停損失效；停牌／成交受限可能超過 20 個交易日。',
                '只比較固定策略，未進行參數最佳化；尚未完成跨年度與獨立樣本外驗證。']
    if len(closed) < 30:
        warnings.append(f'僅 {len(closed)} 筆已平倉交易，樣本不足以推論穩定勝率。')
    if len(active_dates) < 252:
        warnings.append(f'有效模擬僅 {len(active_dates)} 個交易日，不涵蓋完整年度與多種市場循環。')
    if discontinuities:
        warnings.append(f'{len(discontinuities)} 次持股價格異常跳動，可能含公司行動，未做權息調整。')
    if any(p['last_quote_date'] != active_dates[-1] for p in open_positions):
        warnings.append('部分未平倉部位缺少期末行情，以最後收盤估值，淨值與回撤可能不可靠。')
    return {'model_id': model, **MODELS[model], 'status': 'preliminary',
            'data_start': dates[0], 'start': active_dates[0], 'end': active_dates[-1],
            'warmup_sessions': first_index, 'simulated_sessions': len(active_dates),
            'signal_count': signal_count, 'closed_count': len(closed), 'open_count': len(positions),
            'metrics': {'initial_capital': execution.initial_capital, 'final_equity': curve[-1]['equity'],
                        'total_return': round(curve[-1]['equity']/execution.initial_capital-1, 8),
                        'max_drawdown': round(max_drawdown, 8),
                        'win_rate': len(winners)/len(closed) if closed else None,
                        'profit_factor': round(gross_profit/gross_loss, 6) if gross_loss else None,
                        'average_trade_return': mean(t['net_return'] for t in closed) if closed else None,
                        'average_holding_sessions': mean(t['holding_sessions'] for t in closed) if closed else None,
                        'realized_net_pnl': round(sum(t['net_pnl'] for t in closed), 2)},
            'closed_trades': closed, 'open_positions': open_positions, 'equity_curve': curve,
            'rejected_orders': dict(rejected), 'deferred_exits': dict(deferred),
            'warnings': warnings}


def main():
    parser = argparse.ArgumentParser(description='比較 1～4 週波段策略的初步回測（未還原權息）')
    parser.add_argument('--db', default='.state/prices.sqlite3')
    parser.add_argument('--config', default='strategy.json')
    parser.add_argument('--model-config', default='models.json')
    parser.add_argument('--execution-config', default='execution.json')
    parser.add_argument('--output', default='site/backtest.json')
    parser.add_argument('--start', type=date.fromisoformat)
    parser.add_argument('--end', type=date.fromisoformat)
    parser.add_argument('--upstream-error', action='store_true')
    args = parser.parse_args()
    result = {'schema_version': 1, 'status': 'error', 'generated_at': datetime.now(ZoneInfo('Asia/Taipei')).isoformat(), 'models': [], 'errors': []}
    try:
        if args.upstream_error:
            raise DataError('本次官方行情更新失敗，未重新執行回測')
        if not Path(args.db).is_file():
            raise DataError('找不到官方歷史資料庫，請先執行 update')
        p = Parameters(**json.loads(Path(args.config).read_text()))
        execution = Execution(**json.loads(Path(args.execution_config).read_text()))
        model_settings = ModelSettings(**json.loads(Path(args.model_config).read_text()))
        if args.start and args.end and args.start > args.end:
            raise ValueError('回測起日不可晚於迄日')
        store = Store(args.db)
        try:
            end = args.end.isoformat() if args.end else store.latest_date()
            if not end:
                raise DataError('沒有可用的官方歷史行情')
            histories = store.histories(end)
        finally:
            store.close()
        all_dates = sorted({b.date for bars in histories.values() for b in bars})
        common_required = max(required_bars(p, model_settings, model) for model in MODELS)
        if len(all_dates) <= common_required:
            raise DataError('歷史資料不足以在相同區間比較所有策略')
        common_start = max(args.start.isoformat() if args.start else all_dates[0], all_dates[common_required-1])
        result.update(status='preliminary', price_basis='unadjusted',
                      strategy_parameters=asdict(p), execution_parameters=asdict(execution),
                      model_parameters=asdict(model_settings), active_model='trend_pullback', user_model='user_range_reclaim',
                      models=[simulate(histories, p, execution, model, common_start, end, model_settings=model_settings) for model in MODELS])
        code = 0
    except Exception as exc:
        result.update(status='error', models=[], errors=[str(exc)])
        logging.error('回測失敗：%s', exc)
        code = 1
    from .__main__ import write_json
    write_json(Path(args.output), result)
    raise SystemExit(code)


if __name__ == '__main__':
    main()
