"""Synthetic execution paths; these fixtures are never published as market data."""
from dataclasses import replace
from datetime import date, timedelta
import unittest
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from screener.backtest import simulate
from screener.data import Bar, DataError
from screener.execution import Execution, commission, entry_plan, fill_price, tick_price
from screener.models import ModelSettings, alternative, rsi, screen_model
from screener.strategy import Parameters


def dates(n=95):
    result=[];day=date(2025,1,1)
    while len(result)<n:
        if day.weekday()<5:result.append(day.isoformat())
        day+=timedelta(days=1)
    return result


def path(n=95, changes=None, opens=None):
    changes,opens=changes or {},opens or {}
    values=[changes.get(i,100) for i in range(n)]
    return [Bar('TWSE','2330','執行模型測試',d,opens.get(i,values[i-1] if i else 100),
                max(opens.get(i,values[i-1] if i else 100),values[i])+.5,
                min(opens.get(i,values[i-1] if i else 100),values[i])-.5,values[i],1000000)
            for i,d in enumerate(dates(n))]


def signal_for(bar):
    return {'market':bar.market,'code':bar.code,'name':bar.name,'date':bar.date,'close':bar.close,
            'stop':94,'target':120,'support':96,'score':80,'metrics':{'average_volume':1000000}}


def once(histories,day,p):
    assert all(not bars or bars[-1].date<=day for bars in histories.values())
    return {'candidates':[signal_for(histories[('TWSE','2330')][-1])] if day==dates()[64] else []}


class CommandFailureTests(unittest.TestCase):
    def test_upstream_failure_writes_no_fabricated_performance(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'backtest.json'
            command=subprocess.run([sys.executable,'-m','screener.backtest','--upstream-error','--output',str(output)],capture_output=True,text=True)
            self.assertEqual(command.returncode,1)
            report=json.loads(output.read_text())
            self.assertEqual(report['status'],'error')
            self.assertEqual(report['models'],[])
            self.assertIn('官方行情更新失敗',report['errors'][0])


class ExecutionTests(unittest.TestCase):
    def test_tick_rounding_and_costs(self):
        self.assertEqual(tick_price(49.99,True),50)
        self.assertEqual(tick_price(50.01,True),50.1)
        self.assertEqual(tick_price(50.09,False),50)
        self.assertEqual(fill_price(100,True,Execution()),100.5)
        self.assertEqual(commission(1000,Execution()),20)
        for kwargs in ({'max_hold_sessions':5},{'fee_rate':float('nan')},{'lot_size':0},{'slippage_rate':1},{'profit_min_sessions':True}):
            with self.assertRaises(ValueError):Execution(**kwargs)

    def test_entry_plan_is_reference_not_future_fill(self):
        s=signal_for(path()[64]);plan=entry_plan(s,Execution(),Parameters())
        self.assertEqual(plan['entry_timing'],'next_session_open')
        self.assertEqual(plan['max_hold_sessions'],20)
        self.assertLessEqual(plan['maximum_open'],101)


class BacktestTests(unittest.TestCase):
    def run_path(self,bars,**kwargs):
        return simulate({('TWSE','2330'):bars},Parameters(),Execution(),signal_function=once,**kwargs)

    def test_next_open_entry_and_twentieth_session_time_exit(self):
        result=self.run_path(path())
        self.assertEqual(result['closed_count'],1)
        trade=result['closed_trades'][0]
        self.assertEqual(trade['signal_date'],dates()[64])
        self.assertEqual(trade['entry_date'],dates()[65])
        self.assertEqual(trade['exit_date'],dates()[84])
        self.assertEqual(trade['holding_sessions'],20)
        self.assertEqual(trade['exit_reason'],'持有時間到期')
        self.assertLess(trade['net_pnl'],0)  # Flat price still pays fees/tax/slippage.
        self.assertTrue(all(p['cash']>=0 for p in result['equity_curve']))

    def test_stop_earlier_than_week_uses_next_open_with_all_costs(self):
        bars=path(changes={65:93,66:90},opens={66:90})
        result=self.run_path(bars)
        trade=result['closed_trades'][0]
        self.assertEqual(trade['holding_sessions'],2)
        self.assertEqual(trade['exit_date'],dates()[66])
        self.assertEqual(trade['entry_price'],100.5)
        self.assertEqual(trade['exit_price'],89.9)
        self.assertEqual((trade['entry_fee'],trade['exit_fee'],trade['sell_tax']),(143,128,269))
        self.assertEqual(trade['net_pnl'],-11140)
        self.assertEqual(trade['exit_reason'],'收盤停損')

    def test_target_waits_for_minimum_holding_period(self):
        changes={65:108,66:115,67:121,68:121,69:121,70:121}
        trade=self.run_path(path(changes=changes))['closed_trades'][0]
        self.assertEqual(trade['exit_date'],dates()[70])
        self.assertEqual(trade['holding_sessions'],6)
        self.assertEqual(trade['exit_reason'],'收盤達目標')

    def test_gap_cancels_order_instead_of_delayed_fictitious_fill(self):
        result=self.run_path(path(opens={65:102}))
        self.assertEqual(result['closed_count'],0)
        self.assertEqual(result['open_count'],0)
        self.assertEqual(result['rejected_orders']['超過追價上限'],1)
        self.assertIsNone(result['metrics']['win_rate'])

    def test_end_keeps_unclosed_positions_and_future_data_is_ignored(self):
        bars=path()
        end=dates()[68]
        result=self.run_path(bars,end=end)
        mutated=bars[:69]+[replace(b,close=9999,high=10000,low=1) for b in bars[69:]]
        other=self.run_path(mutated,end=end)
        self.assertEqual(result,other)
        self.assertEqual((result['closed_count'],result['open_count']),(0,1))
        self.assertEqual(result['open_positions'][0]['holding_sessions'],4)

    def test_missing_or_locked_down_quote_defers_sale(self):
        bars=path(changes={65:93,66:84,67:85},opens={66:84,67:85})
        result=self.run_path(bars)
        self.assertEqual(result['closed_trades'][0]['exit_date'],dates()[67])
        self.assertEqual(result['deferred_exits']['開盤近跌停，保守假設無法賣出'],1)

    def test_unfilled_open_does_not_use_future_volume_to_choose_alternative(self):
        first=path();first[65]=replace(first[65],volume=500)
        second=[replace(b,market='TPEX',code='6488') for b in path()]
        def signals(known,day,p):
            return {'candidates':[signal_for(known[k][-1]) for k in [('TWSE','2330'),('TPEX','6488')]] if day==dates()[64] else []}
        result=simulate({('TWSE','2330'):first,('TPEX','6488'):second},Parameters(),Execution(initial_capital=200000,max_positions=1),signal_function=signals)
        self.assertEqual(result['closed_count'],0)
        self.assertEqual(result['open_count'],0)
        self.assertEqual(result['rejected_orders']['整張資金或流動性不足'],1)

    def test_insufficient_history_and_reversed_period_fail(self):
        with self.assertRaises(DataError):self.run_path(path(20))
        with self.assertRaises(DataError):self.run_path(path(),start='2099-01-01')


def range_fixture():
    bars=[Bar('TWSE','2330','區間收復測試',d,110,120,100,110,1000000) for d in dates(80)]
    for i in range(70,78):bars[i]=replace(bars[i],open=101,high=103,low=100,close=101)
    bars[78]=replace(bars[78],open=100,high=101,low=98,close=99)
    bars[79]=replace(bars[79],open=101,high=103,low=98,close=102,volume=2000000)
    return bars


def shoulders_fixture():
    bars=[Bar('TWSE','2330','量化頭肩底測試',d,112,113,111,112,1000000) for d in dates(70)]
    for i in (35,55):bars[i]=replace(bars[i],low=109,close=110)
    bars[45]=replace(bars[45],low=100,close=103)
    for i in (40,50):bars[i]=replace(bars[i],high=115)
    bars[68]=replace(bars[68],high=114.5,close=114)
    bars[69]=replace(bars[69],open=114,high=117,low=113,close=116,volume=2000000)
    return bars


class UserModelTests(unittest.TestCase):
    def test_range_reclaim_requires_event_volume_and_defined_base(self):
        bars=range_fixture();p=Parameters()
        result=alternative(bars,p,'user_range_reclaim')
        self.assertIsNotNone(result)
        self.assertEqual(result['variant'],'假跌破後大量收復')
        self.assertEqual(result['support'],100)
        self.assertEqual(result['target'],120)
        self.assertTrue(any('2.00' in x for x in result['reasons']))
        weak=bars[:-1]+[replace(bars[-1],volume=1000000)]
        self.assertIsNone(alternative(weak,p,'user_range_reclaim'))
        deep=bars[:-2]+[replace(bars[-2],low=85),bars[-1]]
        self.assertIsNone(alternative(deep,p,'user_range_reclaim'))
        self.assertIsNone(alternative(bars,p,'user_range_reclaim',replace(ModelSettings(),range_width_max=.1)))

    def test_same_day_false_break_recovery_is_allowed_with_volume(self):
        bars=range_fixture();bars[-2]=replace(bars[-2],open=104,low=103,high=106,close=105)
        result=alternative(bars,Parameters(),'user_range_reclaim')
        self.assertIsNotNone(result)
        self.assertEqual(result['variant'],'假跌破後大量收復')

    def test_head_shoulders_is_confirmed_and_requires_breakout_volume(self):
        bars=shoulders_fixture();p=Parameters()
        result=alternative(bars,p,'user_range_reclaim')
        self.assertIsNotNone(result)
        self.assertEqual(result['variant'],'量化近似頭肩底頸線突破')
        self.assertEqual(result['target'],130)
        weak=bars[:-1]+[replace(bars[-1],volume=1000000)]
        self.assertIsNone(alternative(weak,p,'user_range_reclaim'))
        unconfirmed=bars.copy();unconfirmed[55]=replace(unconfirmed[55],low=111,close=112)
        unconfirmed[68]=replace(unconfirmed[68],low=109)
        self.assertIsNone(alternative(unconfirmed,p,'user_range_reclaim'))

    def test_user_model_is_separate_from_trend_filters_and_future_bars(self):
        bars=range_fixture();day=bars[-1].date
        h={('TWSE','2330'):bars}
        personal=screen_model(h,day,Parameters(),'user_range_reclaim')
        original=screen_model(h,day,Parameters(),'trend_pullback')
        self.assertEqual(len(personal['candidates']),1)
        self.assertEqual(original['candidates'],[])
        h[('TWSE','2330')]=bars+[replace(bars[-1],date='2099-01-01',volume=0)]
        self.assertEqual(screen_model(h,day,Parameters(),'user_range_reclaim'),personal)

    def test_comparison_models_have_positive_paths_and_volume_gate(self):
        closes=[80+i*.2 for i in range(70)]+[100]
        bars=[Bar('TWSE','2330','突破測試',d,c-.2,c+.3,c-.3,c,2000000 if i==70 else 1000000) for i,(d,c) in enumerate(zip(dates(71),closes))]
        self.assertIsNotNone(alternative(bars,Parameters(),'volume_breakout'))
        weak=bars[:-1]+[replace(bars[-1],volume=1000000)]
        self.assertIsNone(alternative(weak,Parameters(),'volume_breakout'))
        closes=[100+i*.5 for i in range(65)]+[130.5,129,127.5,126,124.5,128.5]
        bars=[Bar('TWSE','2330','RSI 測試',d,c-.2,c+.3,c-.3,c,1000000) for d,c in zip(dates(71),closes)]
        bars[64]=replace(bars[64],high=142)
        result=alternative(bars,Parameters(),'rsi_recovery')
        self.assertIsNotNone(result)
        self.assertEqual(result['variant'],'RSI 回升')

    def test_rsi_and_invalid_model_parameters(self):
        self.assertEqual(rsi([100]*20),50)
        self.assertEqual(rsi(list(range(20))),100)
        self.assertEqual(rsi(list(range(20,0,-1))),0)
        for kwargs in ({'range_days':1},{'event_volume_multiple':0},{'recovery_days':1.5},{'head_depth_min':float('nan')}):
            with self.assertRaises(ValueError):ModelSettings(**kwargs)
