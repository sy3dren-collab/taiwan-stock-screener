from dataclasses import replace
import unittest

from test_fusion import fusion_bars
from screener.naked import NakedParameters,evaluate,screen
from screener.naked_backtest import simulate,Risk
from screener.execution import Execution


class RecoveryRevisionTests(unittest.TestCase):
    def setUp(self):
        self.seq=fusion_bars()
        for i in range(110):self.seq[i]=replace(self.seq[i],high=110)
        self.seq[129]=replace(self.seq[129],close=101.8,high=102)
        for i in range(1,len(self.seq)):
            self.seq[i]=replace(self.seq[i],reference=self.seq[i-1].close)
        self.p=NakedParameters(fusion_revision=2,event_days=20)

    def test_causal_recovery_enters_next_open_with_costs(self):
        signal=evaluate(self.seq[:130],'F',self.p)
        self.assertIsNotNone(signal)
        self.assertEqual(signal['fusion_metrics']['range_upper'],110)
        report=simulate({('TWSE','2330'):self.seq},self.p,Execution(),Risk(),'F',
                        self.seq[129].date,self.seq[152].date)
        self.assertEqual(len(report['closed_trades']),1)
        trade=report['closed_trades'][0]
        self.assertEqual(trade['entry_date'],self.seq[130].date)
        self.assertGreater(report['metrics']['total_costs'],0)

    def test_base_ends_at_event_and_failed_newer_event_does_not_hide_it(self):
        seq=self.seq[:130]
        # This bar occurs after the first event: it cannot redraw its base.
        seq[119]=replace(seq[119],high=112,close=111,volume=25000000)
        signal=evaluate(seq,'F',self.p)
        self.assertIsNotNone(signal)
        self.assertEqual(signal['setup_date'],seq[110].date)
        self.assertEqual(signal['fusion_metrics']['range_upper'],110)

    def test_missing_event_volume_and_future_data(self):
        seq=self.seq[:130]
        seq[110]=replace(seq[110],volume=10000000)
        self.assertIsNone(evaluate(seq,'F',self.p))
        day=self.seq[129].date
        expected=screen({('TWSE','2330'):self.seq[:130]},day,'F',self.p)
        altered=self.seq[:130]+[replace(b,open=999,close=999,high=1000,low=990) for b in self.seq[130:]]
        self.assertEqual(screen({('TWSE','2330'):altered},day,'F',self.p),expected)
        self.assertEqual(len(expected['candidates']),1)
