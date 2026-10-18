"""Opt-in integration tests. Require official-host egress and a real trading date."""
from datetime import date, timedelta
import os
import unittest

from screener.__main__ import default_end
from screener.data import OfficialClient


@unittest.skipUnless(os.environ.get('RUN_LIVE_TESTS') == '1', 'opt-in official network integration')
class OfficialIntegrationTests(unittest.TestCase):
    def day(self):
        day=date.fromisoformat(os.environ['LIVE_DATE']) if os.environ.get('LIVE_DATE') else default_end()
        while day.weekday()>=5:
            day-=timedelta(days=1)
        return day

    def check_market(self,market):
        day=self.day()
        bars=OfficialClient().daily(market,day)
        self.assertGreater(len(bars),100,'Choose a confirmed trading day with LIVE_DATE; holidays are not a successful quote integration test')
        self.assertTrue(all(b.market==market and b.date==day.isoformat() and b.volume>=0 for b in bars))

    def test_twse_official_daily_report(self):self.check_market('TWSE')
    def test_tpex_official_daily_report(self):self.check_market('TPEX')
