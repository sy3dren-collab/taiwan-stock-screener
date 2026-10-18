"""Synthetic price paths live only in tests; they are not financial data."""
from dataclasses import replace
from datetime import date, timedelta
import math
import unittest

from screener.data import Bar
from screener.strategy import Parameters, evaluate, pivots, screen


def fixture(code='2330'):
    bars=[]
    n=71
    for i in range(n):
        close=80+i*.3+4*math.sin(i*2*math.pi/10)
        bars.append(Bar('TWSE',code,'僅供測試',(date(2025,1,1)+timedelta(days=i)).isoformat(),close-.2,close+.3,close-.3,close,1000000 if i<n-4 else 500000))
    return bars


def params():
    return Parameters(fast_ma=5,slow_ma=30,slope_days=1,minimum_slope=.0001,pivot_radius=1,
                      structure_days=30,pullback_days=3,volume_baseline_days=5,atr_days=3,
                      stop_atr_buffer=0,min_reward_risk=.2,max_risk_fraction=.3,
                      support_distance_max=.2,min_average_volume=1)


class StrategyTests(unittest.TestCase):
    def test_complete_positive_path_and_risk_formula(self):
        bars=fixture();result=evaluate(bars,params())
        self.assertIsNotNone(result)
        self.assertEqual(len(result['reasons']),5)
        self.assertLess(result['stop'],result['close'])
        self.assertGreater(result['target'],result['close'])
        expected=(result['target']-result['close'])/(result['close']-result['stop'])
        self.assertAlmostEqual(expected,result['reward_risk'],places=2)
        self.assertEqual(result['metrics']['volume_ratio'],.5)

    def test_default_strategy_can_select_without_relaxing_conditions(self):
        bars=[]
        n=110
        for i in range(n):
            close=100+i*.2+2*math.sin(i*2*math.pi/16)
            bars.append(Bar('TWSE','2330','預設策略測試',(date(2025,1,1)+timedelta(days=i)).isoformat(),close-.2,close+.3,close-.3,close,1000000 if i<n-6 else 500000))
        result=evaluate(bars,Parameters())
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result['reward_risk'],1.5)
        self.assertLessEqual(result['metrics']['support_distance'],.04)

    def test_all_five_conditions_can_reject(self):
        bars=fixture();p=params()
        self.assertIsNotNone(evaluate(bars,p))
        self.assertIsNone(evaluate(bars,replace(p,minimum_slope=.5)))
        self.assertIsNone(evaluate(bars,replace(p,structure_days=5)))
        self.assertIsNone(evaluate(bars,replace(p,support_distance_max=.00001)))
        self.assertIsNone(evaluate(bars,replace(p,volume_ratio_max=.1)))
        no_breakout=bars[:-1]+[replace(bars[-1],open=bars[-1].close+.1)]
        self.assertIsNone(evaluate(no_breakout,p))
        self.assertIsNone(evaluate(bars,replace(p,min_reward_risk=10)))
        self.assertIsNone(evaluate(bars,replace(p,max_risk_fraction=.0001)))
        self.assertIsNone(evaluate(bars,replace(p,min_average_volume=99999999)))

    def test_confirmed_pivot_excludes_unconfirmed_last_bar(self):
        bars=fixture()
        high,lows=pivots(bars,2)
        self.assertTrue(high and lows)
        self.assertNotIn(bars[-1],high+lows)
        self.assertNotIn(bars[-2],high+lows)

    def test_gap_and_insufficient_history_excluded(self):
        bars=fixture()
        self.assertIsNone(evaluate(bars[:10],params()))
        self.assertIsNone(evaluate(bars,replace(params(),max_daily_gap=.0001)))

    def test_max_ten_candidates_and_tie_breaking(self):
        histories={('TWSE',str(2000+i)):fixture(str(2000+i)) for i in range(12)}
        result=screen(histories,fixture()[-1].date,params())
        self.assertEqual(result['qualified_count'],12)
        self.assertEqual(len(result['candidates']),10)
        self.assertEqual([c['code'] for c in result['candidates']],[str(2000+i) for i in range(10)])
        self.assertFalse(result['shortfall'])

    def test_no_quota_filling_or_future_leakage(self):
        bars=fixture();end=bars[-1].date
        future=replace(bars[-1],date='2099-01-01',close=.01)
        expected=screen({('TWSE','2330'):bars},end,params())
        result=screen({('TWSE','2330'):bars+[future]},end,params())
        self.assertEqual(result,expected)
        self.assertEqual(len(result['candidates']),1)
        self.assertTrue(result['shortfall'])
        self.assertEqual(len(screen({('TWSE','2330'):bars},'2025-05-01',params())['candidates']),0)

    def test_invalid_parameters_fail_early(self):
        for kwargs in ({'fast_ma':70},{'max_candidates':11},{'atr_days':0},{'pivot_radius':1.5},
                       {'volume_ratio_max':float('nan')},{'volume_ratio_max':1.1},
                       {'minimum_slope':True},{'min_reward_risk':0},{'unknown':1}):
            with self.assertRaises((ValueError,TypeError)):Parameters(**kwargs)
