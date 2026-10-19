"""Meaningful checks for frozen refinements, coverage and no future information."""
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from screener.backtest import simulate
from screener.data import DataError, Store
from screener.execution import Execution
from screener.models import ModelSettings, alternative, screen_model, wilder_rsi
from screener.refinements import Refinements, refined_screen
from screener.research import diagnose, run_research, validation_start, verify_coverage, verdict, year_start
from screener.strategy import Parameters
from test_backtest import dates, path, range_fixture, signal_for


def strong_range():
    bars=range_fixture()
    for i in range(70):bars[i]=replace(bars[i],open=108,close=108,high=110,low=105)
    bars[10]=replace(bars[10],high=120,low=100)
    return bars


class ResearchTests(unittest.TestCase):
    def test_calendar_year_and_eight_month_split(self):
        self.assertEqual(year_start('2026-10-16'),'2025-10-17')
        self.assertEqual(year_start('2024-02-29'),'2023-03-01')
        self.assertEqual(validation_start('2025-10-17'),'2026-06-17')
        self.assertEqual(validation_start('2025-06-30'),'2026-02-28')

    def test_missing_ledger_day_is_not_assumed_to_be_holiday(self):
        bars=path()
        with tempfile.TemporaryDirectory() as d:
            store=Store(str(Path(d)/'history.db'))
            try:
                for b in bars:
                    store.save_day(date.fromisoformat(b.date),{'TWSE':[b],'TPEX':[replace(b,market='TPEX',code='6488')]})
                store.db.commit()
                coverage=verify_coverage(store,{('TWSE','2330'):bars},bars[70].date,bars[-1].date,70)
                self.assertEqual(coverage['checked_through'],bars[-1].date)
                store.db.execute('DELETE FROM sessions WHERE date=?',(bars[80].date,))
                with self.assertRaisesRegex(DataError,'覆蓋有缺漏'):
                    verify_coverage(store,{('TWSE','2330'):bars},bars[70].date,bars[-1].date,70)
            finally:store.close()

    def test_coverage_rejects_completed_session_with_missing_market_rows(self):
        bars=path();store=Store(':memory:')
        try:
            for b in bars:store.save_day(date.fromisoformat(b.date),{'TWSE':[b],'TPEX':[replace(b,market='TPEX',code='6488')]})
            store.db.execute("DELETE FROM bars WHERE date=? AND market='TPEX'",(bars[80].date,))
            with self.assertRaisesRegex(DataError,'筆數與完成紀錄不符'):
                verify_coverage(store,{('TWSE','2330'):bars},bars[70].date,bars[-1].date,70)
        finally:store.close()

    def test_no_shortened_year_when_warmup_is_missing(self):
        bars=path()
        with self.assertRaisesRegex(DataError,'暖機'):
            run_research({('TWSE','2330'):bars},Parameters(),Execution(),ModelSettings(),Refinements(),end=bars[-1].date)

    def test_wilder_reference_calculation_and_validation(self):
        closes=[44.34,44.09,44.15,43.61,44.33,44.83,45.10,45.42,45.84,46.08,45.89,46.03,45.61,46.28,46.28]
        self.assertAlmostEqual(wilder_rsi(closes),70.464135,places=5)
        self.assertEqual(wilder_rsi([100]*20),50)
        self.assertEqual(wilder_rsi(list(range(20))),100)
        with self.assertRaises(ValueError):wilder_rsi([1,2])
        with self.assertRaises(ValueError):ModelSettings(rsi_wilder=1)
        for kwargs in ({'risk_budget_fraction':1},{'failure_sessions':1.5},{'minimum_close_location':1.1},{'max_atr_fraction':float('nan')}):
            with self.assertRaises(ValueError):Refinements(**kwargs)

    def test_personal_refinement_preserves_mandatory_volume_and_independence(self):
        bars=strong_range();day=bars[-1].date;p=Parameters()
        result=refined_screen({('TWSE','2330'):bars},day,p,'user_range_reclaim')
        self.assertEqual(len(result['candidates']),1)
        self.assertEqual(screen_model({('TWSE','2330'):bars},day,p,'trend_pullback')['candidates'],[])
        weak=bars[:-1]+[replace(bars[-1],volume=1000000)]
        self.assertEqual(refined_screen({('TWSE','2330'):weak},day,p,'user_range_reclaim')['candidates'],[])
        not_confirmed=bars.copy();not_confirmed[-2]=replace(bars[-2],high=102.5)
        self.assertIsNotNone(alternative(not_confirmed,p,'user_range_reclaim'))
        self.assertEqual(refined_screen({('TWSE','2330'):not_confirmed},day,p,'user_range_reclaim')['candidates'],[])
        future=bars+[replace(bars[-1],date='2099-01-01',close=999,high=999)]
        self.assertEqual(result,refined_screen({('TWSE','2330'):future},day,p,'user_range_reclaim'))

    def test_omitting_chart_payload_does_not_change_signals(self):
        bars=strong_range();h={('TWSE','2330'):bars};day=bars[-1].date
        normal=screen_model(h,day,Parameters(),'user_range_reclaim')
        lean=screen_model(h,day,Parameters(),'user_range_reclaim',include_bars=False)
        self.assertTrue(normal['candidates'][0]['bars'])
        normal['candidates'][0]['bars']=[]
        self.assertEqual(normal,lean)

    def test_breakout_refinement_rejects_overextension(self):
        from screener.data import Bar
        closes=[80+i*.2 for i in range(70)]+[100]
        bars=[Bar('TWSE','2330','突破測試',d,c-.2,c+.3,c-.3,c,2000000 if i==70 else 1000000) for i,(d,c) in enumerate(zip(dates(71),closes))]
        self.assertIsNotNone(alternative(bars,Parameters(),'volume_breakout'))
        self.assertEqual(refined_screen({('TWSE','2330'):bars},bars[-1].date,Parameters(),'volume_breakout')['candidates'],[])
        bars[-1]=replace(bars[-1],open=93.8,close=94.2,high=94.3,low=93.7)
        self.assertEqual(len(refined_screen({('TWSE','2330'):bars},bars[-1].date,Parameters(),'volume_breakout')['candidates']),1)

    def test_trend_refinement_requires_volume_on_resumption_day(self):
        import math
        from screener.data import Bar
        bars=[]
        for i,d in enumerate(dates(110)):
            c=100+i*.2+2*math.sin(i*2*math.pi/16)
            bars.append(Bar('TWSE','2330','回檔測試',d,c-.2,c+.1,c-.5,c,1000000 if i<104 else 500000))
        h={('TWSE','2330'):bars};day=bars[-1].date
        self.assertEqual(len(screen_model(h,day,Parameters(),'trend_pullback')['candidates']),1)
        self.assertEqual(refined_screen(h,day,Parameters(),'trend_pullback')['candidates'],[])
        bars[-1]=replace(bars[-1],volume=1000000)
        self.assertEqual(len(refined_screen(h,day,Parameters(),'trend_pullback')['candidates']),1)

    def test_rsi_refinement_uses_wilder_midline_and_has_valid_positive_path(self):
        import random
        from screener.data import Bar
        rng=random.Random(17);price=100;bars=[]
        for d in dates(177):
            price=max(20,price+.15+rng.gauss(0,1))
            bars.append(Bar('TWSE','2330','純測試RSI',d,price-.3,price+.1,price-.5,price,1000000))
        # A historical resistance outside ATR14 provides sufficient upside room.
        bars[-20]=replace(bars[-20],high=max(bars[-20].high,price*1.1))
        result=refined_screen({('TWSE','2330'):bars},bars[-1].date,Parameters(),'rsi_recovery')
        self.assertEqual(len(result['candidates']),1)
        self.assertIn('Wilder 平滑',result['candidates'][0]['reasons'][0])
        self.assertIn('穿越 50',result['candidates'][0]['reasons'][0])
        weak=bars[:-1]+[replace(bars[-1],volume=900000)]
        self.assertEqual(refined_screen({('TWSE','2330'):weak},bars[-1].date,Parameters(),'rsi_recovery')['candidates'],[])

    def test_capital_risk_budget_is_enforced_at_next_open(self):
        bars=path()
        def signal(known,day,p):
            s=signal_for(known[('TWSE','2330')][-1]);s.update(stop=96,target=120)
            return {'candidates':[s] if day==dates()[64] else []}
        r=simulate({('TWSE','2330'):bars},Parameters(),Execution(initial_capital=1000000,max_positions=1),signal_function=signal,refinement_settings=Refinements())
        trade=r['closed_trades'][0]
        self.assertEqual(trade['quantity'],2000)
        self.assertLessEqual(trade['quantity']*(trade['entry_price']-trade['initial_stop']),10000)
        self.assertEqual(trade['exit_reason'],'轉強未延續，時間失敗出場')
        self.assertEqual(trade['holding_sessions'],6)

    def test_protective_stop_uses_only_previous_closing_information(self):
        bars=path(changes={65:106,66:100,67:99},opens={67:99})
        def signal(known,day,p):
            s=signal_for(known[('TWSE','2330')][-1]);s.update(stop=96,target=120)
            return {'candidates':[s] if day==dates()[64] else []}
        r=simulate({('TWSE','2330'):bars},Parameters(),Execution(),signal_function=signal,refinement_settings=Refinements())
        t=r['closed_trades'][0]
        self.assertEqual(t['initial_stop'],96)
        self.assertEqual(t['stop'],t['entry_price'])
        self.assertEqual(t['exit_date'],dates()[67])
        self.assertEqual(t['exit_reason'],'收盤停損')
        self.assertLess(t['net_pnl'],0) # A gross breakeven level is not a guaranteed net profit.

    def test_diagnostic_excludes_exit_day_intraday_prices(self):
        bars=path();trade={'market':'TWSE','code':'2330','signal_variant':'fixture','exit_reason':'stop','exit_date':bars[67].date,'entry_date':bars[65].date,'entry_price':100,'net_pnl':-1}
        bars[67]=replace(bars[67],high=9999,low=1)
        r={'closed_trades':[trade],'equity_curve':[{'positions':1,'equity':100000,'cash':80000}]}
        d=diagnose(r,{('TWSE','2330'):bars})
        self.assertLess(trade['maximum_favorable_excursion'],.01)
        self.assertGreater(trade['maximum_adverse_excursion'],-.01)
        self.assertAlmostEqual(d['mean_exposure'],.2)
        self.assertEqual(d['longest_losing_streak'],1)

    def test_verdict_requires_samples_and_both_periods(self):
        def result(ret,dd=.05,n=40):return {'closed_count':n,'metrics':{'total_return':ret,'max_drawdown':dd}}
        good={'baseline':result(-.1,.1),'candidate':result(.03)}
        self.assertIn('改善',verdict(good,good))
        bad={'baseline':result(.1),'candidate':result(-.1)}
        self.assertIn('尚未證明',verdict(good,bad))
        tiny={'baseline':result(.1,n=2),'candidate':result(.2,n=3)}
        self.assertIn('樣本不足',verdict(tiny,tiny))

    def test_cached_simulation_windows_are_independent_and_original_preserved(self):
        bars=path(335)
        h={('TWSE','2330'):bars}
        def stream(known,day,p,*args,**kwargs):return {'candidates':[]}
        with patch('screener.research.screen_model',side_effect=stream),patch('screener.research.refined_screen',side_effect=stream):
            r=run_research(h,Parameters(),Execution(),ModelSettings(),Refinements(),start=bars[70].date,end=bars[-1].date)
        self.assertEqual(len(r['models']),4)
        self.assertFalse(r['research_protocol']['parameter_search'])
        for model in r['models']:
            exp=model['experiment']
            self.assertFalse(exp['promoted'])
            self.assertEqual(model['start'],exp['candidate']['start'])
            self.assertLess(exp['development']['baseline']['end'],exp['validation']['baseline']['start'])
            self.assertEqual(exp['validation']['baseline']['metrics']['initial_capital'],1000000)
            self.assertEqual(exp['validation']['candidate']['metrics']['total_return'],0)
