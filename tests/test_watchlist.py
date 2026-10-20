from dataclasses import replace
import json
from pathlib import Path
import unittest

from screener.watchlist import evaluator
from screener.naked import NakedParameters
from test_naked import bars


class WatchlistTests(unittest.TestCase):
    def setUp(self):
        self.config=json.loads(Path('watchlist.json').read_text())
        self.observe=evaluator(self.config)
        self.seq=bars(101);self.p=NakedParameters()

    def test_early_observation_is_not_entry_or_an_invented_event(self):
        result=self.observe(self.seq,'F',self.p)
        self.assertIsNotNone(result)
        self.assertTrue(result['observation_only'])
        self.assertFalse(result['entry_confirmed'])
        self.assertEqual(result['variant'],'整理觀察，等待放量事件')
        self.assertTrue(result['waiting_conditions'])

    def test_declining_or_extended_stock_is_not_added_to_fill_a_quota(self):
        seq=self.seq[:];seq[-1]=replace(seq[-1],close=80,open=81,low=79,high=82)
        self.assertIsNone(self.observe(seq,'F',self.p))
        seq=self.seq[:];seq[-1]=replace(seq[-1],close=120,open=119,low=119,high=121)
        self.assertIsNone(self.observe(seq,'F',self.p))

    def test_recent_event_is_labelled_and_scored_above_early_observation(self):
        plain=self.observe(self.seq,'F',self.p)
        seq=self.seq[:];seq[-1]=replace(seq[-1],open=100,close=102,high=102.2,low=99.5,volume=20000000)
        result=self.observe(seq,'F',self.p)
        self.assertEqual(result['variant'],'事件後等待回測轉強')
        self.assertGreater(result['score'],plain['score'])
        self.assertFalse(result['entry_confirmed'])

    def test_falling_mean_or_excessive_daily_ranges_are_rejected(self):
        seq=self.seq[:]
        for i in range(81,101):
            close=98 if i<96 else 99
            seq[i]=replace(seq[i],open=close,close=close,low=close-.5,high=close+.5)
        self.assertIsNone(self.observe(seq,'F',self.p))
        seq=[replace(b,high=104,low=96) for b in self.seq]
        self.assertIsNone(self.observe(seq,'F',self.p))

    def test_observation_admission_does_not_relax_entry_price_or_liquidity(self):
        from unittest.mock import patch
        strict=replace(self.p,minimum_price=20,minimum_turnover=50000000)
        admission=replace(self.p,minimum_price=10,minimum_turnover=20000000)
        with patch('screener.watchlist.evaluate',return_value=None) as check:
            evaluator(self.config,strict_parameters=strict)(self.seq,'F',admission)
        self.assertEqual(check.call_args.args[2],strict)
