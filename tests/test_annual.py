"""Synthetic fixtures only; exercise admission, action accounting and fail-closed runs."""
from dataclasses import replace
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from screener.annual import GuardedSignals,RequestGate,VARIANTS,audit_year,backfill_year,run_year
from screener.data import DataError,Store,URLS
from screener.distributions import parse_distributions,fetch_distributions,reconcile_distributions
from screener.execution import Execution
from screener.naked import NakedParameters
from screener.naked_backtest import simulate,Risk
from screener.quality import actions,CorporateAction
from screener.reporting import record_run
from test_fusion import fusion_bars
from test_naked import bars,execute


def twse_events(kind='息'):
    return {'stat':'OK','fields':['資料日期','股票代號','除權息前收盤價','除權息參考價','權/息','開盤競價基準','權值+息值'],
            'data':[['114年01月06日','2330','100','98.97',kind,'99','1.03']]}


def tpex_events():
    return {'stat':'ok','tables':[{'fields':['除權息日期','代號','除權息前收盤價','除權息參考價','權/息','開始交易基準價','現金股利','每仟股無償配股','現金增資股數'],
                                'totalCount':1,'data':[['114/01/06','6488','100','99','除息','99','1','0','0']]}]}


class DistributionTests(unittest.TestCase):
    def test_only_cash_is_importable_and_rounded_base_is_distinct(self):
        r=parse_distributions('TWSE',twse_events(),'2025-01-01','2025-12-31')[0]
        self.assertEqual(r['cash'],1.03);self.assertEqual(r['reference'],99);self.assertEqual(r['after'],98.97)
        mixed=parse_distributions('TWSE',twse_events('權息'),'2025-01-01','2025-12-31')[0]
        self.assertFalse(mixed['supported']);self.assertIsNone(mixed['cash'])
        self.assertEqual(parse_distributions('TPEX',tpex_events(),'2025-01-01','2025-12-31')[0]['cash'],1)

    def test_truncated_wrong_period_or_failed_response_is_not_empty_calendar(self):
        bad=tpex_events();bad['tables'][0]['totalCount']=2
        for market,payload,start in [('TPEX',bad,'2025-01-01'),('TWSE',twse_events(),'2026-01-01'),('TWSE',{'stat':'error'},'2025-01-01')]:
            with self.assertRaises(DataError):parse_distributions(market,payload,start,'2026-12-31')

    def test_official_sources_restore_special_reference_and_accrue_exact_cash(self):
        s=Store(':memory:')
        try:
            previous=replace(bars()[0],date='2025-01-03')
            current=replace(previous,date='2025-01-06',reference=None,close=99)
            for b in [previous,current]:
                s.save_day(date.fromisoformat(b.date),{'TWSE':[b],'TPEX':[replace(b,market='TPEX',code='6488')]})
            fetch_distributions(s,'2025-01-01','2025-12-31',lambda u:twse_events() if 'twse.com' in u else tpex_events())
            r=reconcile_distributions(s,'2025-01-01','2025-12-31')
            self.assertEqual(r['references_restored'],2);self.assertEqual(r['cash_events_imported'],2)
            a=next(a for a in actions(s) if a.market=='TWSE')
            self.assertAlmostEqual(a.price_factor,.9897);self.assertEqual(a.reference_price,99)
            self.assertEqual(a.cash_per_share,1.03);self.assertIsNone(a.payable_date)
            self.assertEqual(a.announced_date,a.effective_date)
            self.assertEqual(reconcile_distributions(s,'2025-01-01','2025-12-31')['references_restored'],0)
            self.assertEqual(s.db.execute('SELECT COUNT(*) FROM corporate_source_evidence').fetchone()[0],2)
            self.assertFalse(s.db.execute("SELECT name FROM sqlite_master WHERE name='lifecycle_coverage'").fetchall())
        finally:s.close()

    def test_explicit_official_base_does_not_require_theoretical_factor_to_round_identically(self):
        seq=bars();effective=seq[103].date
        for i in range(103,len(seq)):seq[i]=replace(seq[i],open=99,high=99.5,low=98.5,close=99,reference=99)
        event=CorporateAction('cash-rounded','TWSE','2330',effective,effective,'distribution','https://www.twse.com.tw/event',.9897,1,1.03,99)
        result=execute(seq,events=[event]);self.assertEqual(result['closed_trades'][0]['dividends'],1.03*result['closed_trades'][0]['quantity'])
        self.assertGreater(result['metrics']['net_return'],-.02)


class AnnualAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.seq=fusion_bars();self.p=NakedParameters(**json.loads(Path('naked_k.json').read_text())['signal'])
        self.sessions=[b.date for b in self.seq];self.day=self.seq[129].date

    def test_unknown_event_excludes_only_affected_stock_and_cannot_erase_other_signals(self):
        other=[replace(b,code='2331') for b in self.seq[:130]]
        broken=self.seq[:130];broken[110]=replace(broken[110],reference=80)
        provider=GuardedSignals(self.p,[],self.sessions)
        r=provider({('TWSE','2330'):broken,('TWSE','2331'):other},self.day)
        self.assertEqual([s['code'] for s in r['candidates']],['2331'])
        self.assertEqual(provider.counts['unresolved_reference_or_event'],1)

    def test_future_barrier_does_not_change_today_but_known_unsupported_event_blocks(self):
        hist={('TWSE','2330'):self.seq[:130]}
        expected=GuardedSignals(self.p,[],self.sessions)(hist,self.day)
        self.assertEqual(len(expected['candidates']),1)
        future={'market':'TWSE','code':'2330','date':self.seq[131].date,'kind':'權'}
        self.assertEqual(GuardedSignals(self.p,[],self.sessions,[future])(hist,self.day),expected)
        past={**future,'date':self.seq[110].date}
        self.assertEqual(GuardedSignals(self.p,[],self.sessions,[past])(hist,self.day)['candidates'],[])

    def test_suspension_and_missing_reference_reset_only_known_history(self):
        for seq in [self.seq[:80]+self.seq[81:130],[replace(b,reference=None) if i==80 else b for i,b in enumerate(self.seq[:130])]]:
            provider=GuardedSignals(self.p,[],self.sessions)
            self.assertEqual(provider({('TWSE','2330'):seq},self.day)['candidates'],[])

    def test_held_unsupported_event_aborts_instead_of_removing_losing_position(self):
        barrier={'market':'TWSE','code':'2330','date':self.seq[135].date,'kind':'權'}
        with self.assertRaisesRegex(DataError,'持倉遇尚未支援'):
            simulate({('TWSE','2330'):self.seq},self.p,Execution(),Risk(),'F',self.day,self.seq[-1].date,security_barriers=[barrier])


class AnnualIntegrationTests(unittest.TestCase):
    def test_predeclared_variant_changes_one_rule_without_altering_cost_or_formal_strategy(self):
        p=NakedParameters(**json.loads(Path('naked_k.json').read_text())['signal'])
        changed=replace(p,**VARIANTS['wider-range']['changes'])
        from dataclasses import asdict
        self.assertEqual([k for k,v in asdict(p).items() if asdict(changed)[k]!=v],['range_width'])
        self.assertEqual(p.range_width,.25);self.assertEqual(changed.range_width,.30)
        self.assertIsNone(json.loads(Path('strategy_registry.json').read_text())['active_strategy'])
        wide=fusion_bars()[:130]
        for i in range(50,110):wide[i]=replace(wide[i],high=121)
        from screener.naked import evaluate
        self.assertIsNone(evaluate(wide,'F',p))
        self.assertIsNotNone(evaluate(wide,'F',changed))
    def test_parallel_fetches_share_one_per_host_rate_and_attempt_budget(self):
        clock=[100.0]
        with patch('screener.annual.time.monotonic',lambda:clock[0]),patch('screener.annual.time.sleep',lambda seconds:clock.__setitem__(0,clock[0]+seconds)):
            gate=RequestGate(3,200)
            gate('TWSE');gate('TPEX');self.assertEqual(clock[0],100)
            gate('TWSE');self.assertEqual(clock[0],101)
            with self.assertRaisesRegex(DataError,'預算已用完'):gate('TPEX')
            self.assertEqual(gate.count,3)
    def test_failed_market_never_commits_partial_day_and_cache_retries_are_bounded(self):
        s=Store(':memory:')
        class Client:
            def __init__(self,**kw):self.request_count=0;self.provenance={}
            def daily(self,market,day):
                self.request_count+=1
                if market=='TPEX':raise DataError('official failure')
                self.provenance[market]={'url':URLS[market]+'?date=test','sha256':'a'*64,'fetched_at':'2025-01-06T00:00:00Z'}
                return [replace(bars()[0],date=day.isoformat())]
        cfg={'data_start':'2025-01-06','end':'2025-01-07','max_backfill_dates':1,'max_requests':10,'backfill_seconds':5}
        try:
            r=backfill_year(s,cfg,Client)
            self.assertEqual(r['status'],'error');self.assertEqual(r['http_requests'],2)
            self.assertEqual(s.db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0],0)
            self.assertEqual(s.db.execute('SELECT COUNT(*) FROM ingestion_runs').fetchone()[0],1)
        finally:s.close()

    def test_complete_diagnostic_produces_real_engine_trade_without_promotion_or_holdout_relabel(self):
        s=Store(':memory:');seq=fusion_bars()
        try:
            for b in seq:
                proof={m:{'url':URLS[m]+'?date=test','sha256':'a'*64,'fetched_at':'2025-01-06T00:00:00Z'} for m in URLS}
                s.save_day(date.fromisoformat(b.date),{'TWSE':[b],'TPEX':[replace(b,market='TPEX',code='6488')]},proof)
            from screener.distributions import event_tables
            event_tables(s)
            for market in URLS:s.db.execute('INSERT INTO distribution_sources VALUES (?,?,?,?,?,?)',(market,seq[0].date,seq[-1].date,'https://www.twse.com.tw/test','a'*64,'test'))
            s.db.commit()
            cfg={'data_start':seq[0].date,'start':seq[101].date,'end':seq[-1].date,'simulation_seconds':5}
            q=audit_year(s,cfg);self.assertEqual(q['status'],'diagnostic_ready')
            self.assertFalse(q['promotion_allowed']);self.assertFalse(q['formal_research_ready'])
            r=run_year(s,cfg)
            self.assertEqual(r['status'],'completed');self.assertEqual(r['strategy']['metrics']['closed_count'],2)
            self.assertLess(r['strategy']['metrics']['net_return'],0);self.assertFalse(r['promotion_allowed']);self.assertIsNone(r['active_strategy'])
            self.assertEqual(r['strategy']['closed_trades'][0]['entry_date'],seq[130].date)
            self.assertGreater(r['strategy']['metrics']['total_costs'],0)
            with tempfile.TemporaryDirectory() as d:
                run=record_run(r,'annual-research',d,Path(d)/'runs',Path(d)/'site')
                self.assertEqual(run['completed_experiments'],1)
                t=run['trials'][0];self.assertEqual(t['report_kind'],'annual_diagnostic');self.assertIsNone(t['mean_validation_return'])
                self.assertEqual(t['annual_net_return'],r['strategy']['metrics']['net_return'])
                self.assertIn('一年帳戶淨報酬',Path(d,'site/latest-backtest.md').read_text())
            # A missing official weekday must still block the entire diagnostic.
            with s.db:s.db.execute('DELETE FROM source_batches WHERE date=?',(seq[105].date,))
            self.assertEqual(run_year(s,cfg)['status'],'blocked')
        finally:s.close()


if __name__=='__main__':unittest.main()
