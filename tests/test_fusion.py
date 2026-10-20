from dataclasses import replace
import json,unittest
from pathlib import Path

from screener.naked import NakedParameters,NAMES,evaluate,screen
from screener.naked_backtest import simulate,Risk
from screener.execution import Execution
from screener.models import MODELS,alternative,screen_model
from screener.refinements import refined_screen
from screener.strategy import Parameters
from test_naked import bars


def fusion_bars():
    seq=[replace(b,open=100,high=105,low=95,close=100,volume=10000000) for b in bars(155)]
    values=[(94.5,97,94,96),(97,99,96,98),(99,101,97,100),(101,102,99,101),
            (102,104,101,103),(102,103,100,102),(100,101,99,100),(100,102,99,101),
            (99,101,98,100),(100,102,99,101),(101,104,100,103),(103,105,102,104),
            (104,106,103,105),(106,108,104,107),(104,106,102,104),(102,104,100,101),
            (100,102,99,100),(99,100,98.3,99),(99,99.7,98.1,98.8),(98.8,100.2,98.2,100)]
    for i,(o,h,l,c) in enumerate(values,110):seq[i]=replace(seq[i],open=o,high=h,low=l,close=c)
    seq[110]=replace(seq[110],volume=20000000)
    for i in range(124,129):seq[i]=replace(seq[i],volume=5000000)
    seq[129]=replace(seq[129],volume=15000000)
    for i in range(130,len(seq)):seq[i]=replace(seq[i],high=100.5,low=99.5)
    for i in range(1,len(seq)):seq[i]=replace(seq[i],reference=seq[i-1].close)
    return seq


class FusionTests(unittest.TestCase):
    def setUp(self):self.p=replace(NakedParameters(**json.loads(Path('naked_k.json').read_text())['signal']),fusion_revision=1);self.seq=fusion_bars()
    def test_exactly_one_current_strategy_and_rsi_is_removed_from_all_execution_routes(self):
        self.assertEqual(set(NAMES),{'F'});self.assertNotIn('rsi_recovery',MODELS)
        for fn in [lambda:alternative(self.seq,Parameters(),'rsi_recovery'),
                   lambda:screen_model({},self.seq[129].date,Parameters(),'rsi_recovery'),
                   lambda:refined_screen({},self.seq[129].date,Parameters(),'rsi_recovery')]:
            with self.assertRaises(ValueError):fn()
    def test_three_strengths_form_one_positive_causal_sequence(self):
        s=evaluate(self.seq[:130],'F',self.p)
        self.assertIsNotNone(s);self.assertEqual(s['setup_date'],self.seq[110].date)
        self.assertEqual(s['variant'],'大量假跌破收復');self.assertEqual(s['model_id'],'F')
        self.assertGreaterEqual(s['fusion_metrics']['setup_volume_ratio'],1.5)
        self.assertLessEqual(s['fusion_metrics']['pullback_volume_ratio'],.8)
        self.assertGreaterEqual(s['fusion_metrics']['entry_volume_ratio'],1.2)
        self.assertEqual(s['target'],105);self.assertGreater(s['reward_risk'],1.5)
    def test_missing_setup_volume_or_entry_volume_is_rejected(self):
        for i,vol in [(110,10000000),(129,6000000)]:
            seq=self.seq[:130];seq[i]=replace(seq[i],volume=vol)
            self.assertIsNone(evaluate(seq,'F',self.p))
    def test_breakout_uses_the_same_trend_retest_entry_instead_of_chasing(self):
        seq=self.seq[:130]
        values=[(105.5,106.5,104.9,106),(106.8,108,106,107.5),(108,109,107,108),
                (106,108,105,106),(108,109,106,108),(109,110,107,109),(111,112,108,111),
                (109,110,107,109),(108,109,107,108),(109,110,107.5,109),(107,108,106,107),
                (108,110,107.2,109),(110,112,108,111),(112,113,110,112.5),(114,115,111,114),
                (110,112,108,110),(109,110,107,109),(107,109,106.3,108),(107,107.7,106.1,106.8),(107,108.3,106.2,108)]
        for i,(o,h,l,c) in enumerate(values,110):seq[i]=replace(seq[i],open=o,high=h,low=l,close=c)
        signal=evaluate(seq,'F',self.p)
        self.assertIsNotNone(signal);self.assertEqual(signal['variant'],'大量突破整理上緣')
        self.assertEqual(signal['target'],115);self.assertGreater(signal['date'],signal['setup_date'])
    def test_no_entry_on_setup_or_during_expanding_pullback(self):
        self.assertIsNone(evaluate(self.seq[:111],'F',self.p))
        seq=self.seq[:130]
        for i in range(124,129):seq[i]=replace(seq[i],volume=30000000)
        self.assertIsNone(evaluate(seq,'F',self.p))
    def test_failed_rising_structure_or_missing_turnover_is_rejected(self):
        seq=self.seq[:130];seq[123]=replace(seq[123],high=103.5,open=103,close=103.2,low=102)
        # A lower most recent confirmed high cannot satisfy the rising-structure stage.
        self.assertIsNone(evaluate(seq,'F',self.p))
        self.assertIsNone(evaluate([replace(b,turnover=None) for b in self.seq[:130]],'F',self.p))
    def test_future_bars_and_unconfirmed_low_cannot_change_signal(self):
        seq=self.seq;day=seq[129].date
        expected=screen({('TWSE','2330'):seq[:130]},day,'F',self.p)
        altered=seq[:130]+[replace(b,close=999,high=1000,low=990,open=995) for b in seq[130:]]
        self.assertEqual(screen({('TWSE','2330'):altered},day,'F',self.p),expected)
        self.assertEqual(len(expected['candidates']),1)
    def test_actual_fusion_signal_fills_next_open_and_records_costs(self):
        r=simulate({('TWSE','2330'):self.seq},self.p,Execution(),Risk(),'F',self.seq[129].date,self.seq[152].date)
        self.assertEqual(len(r['closed_trades']),1);t=r['closed_trades'][0]
        self.assertEqual(t['signal_date'],self.seq[129].date);self.assertEqual(t['entry_date'],self.seq[130].date)
        self.assertEqual(t['holding_sessions'],20);self.assertGreater(r['metrics']['total_costs'],0)
        self.assertLess(t['net_pnl'],0)
