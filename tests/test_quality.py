from dataclasses import replace
from datetime import date
import hashlib,json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from screener.data import Store,DataError,parse_report
from screener.quality import CorporateAction,adjusted_history,signal_histories,import_actions,actions,backfill,audit_dataset,fingerprint
from test_data import twse,tpex,DAY
from test_backtest import path

class QualityTests(unittest.TestCase):
    def test_official_amount_and_current_reference_not_next_day(self):
        r=twse();r['fields9']+=['成交金額','漲跌(+/-)','漲跌價差'];r['data9'][0]+=['123456789','<p>+</p>','4'];r['data9'][1]+=['100','+','0']
        b=parse_report('TWSE',DAY,r)[0];self.assertEqual((b.turnover,b.reference),(123456789,100))
        r=tpex();r['tables'][0]['fields']+=['成交金額(千元)','次日 參考價'];r['tables'][0]['data'][0]+=['123,000','99']
        b=parse_report('TPEX',DAY,r)[0];self.assertEqual((b.turnover,b.reference),(123000000,100))
        self.assertIsNone(parse_report('TWSE',DAY,twse())[0].turnover)

    def test_old_sqlite_migration_keeps_rows_without_fabricated_amount(self):
        with tempfile.TemporaryDirectory() as d:
            p=str(Path(d)/'old.db');db=sqlite3.connect(p)
            db.execute('CREATE TABLE bars(market TEXT,code TEXT,name TEXT,date TEXT,open REAL,high REAL,low REAL,close REAL,volume INTEGER,PRIMARY KEY(market,code,date))')
            db.execute("INSERT INTO bars VALUES ('TWSE','2330','test','2025-01-06',100,105,98,104,1000)");db.commit();db.close()
            s=Store(p)
            try:self.assertIsNone(s.histories('2025-01-06')[('TWSE','2330')][0].turnover)
            finally:s.close()

    def event(self,**kwargs):
        values=dict(event_id='split-1',market='TWSE',code='2330',effective_date='2025-04-03',announced_date='2025-04-01',kind='split',source_url='https://www.twse.com.tw/event',price_factor=.5,share_factor=2,reference_price=50)
        values.update(kwargs);return CorporateAction(**values)

    def test_only_known_effective_actions_adjust_signal_prices(self):
        bars=path();event=self.event(effective_date=bars[70].date,announced_date=bars[65].date)
        before=adjusted_history(bars,bars[69].date,[event]);self.assertEqual(before[-1].close,100)
        after=adjusted_history(bars,bars[70].date,[event]);self.assertEqual(after[0].close,50);self.assertEqual(after[0].volume,2000000)
        self.assertEqual(bars[0].close,100);self.assertEqual(bars[0].volume,1000000)

    def test_identity_is_point_in_time_and_events_are_not_overwritten(self):
        bars=path();event=self.event(kind='identity',price_factor=1,share_factor=1,new_market='TPEX',new_code='6488',effective_date=bars[70].date,announced_date=bars[65].date)
        new=[replace(b,market='TPEX',code='6488') for b in bars[70:]];h={('TWSE','2330'):bars[:70],('TPEX','6488'):new}
        self.assertIn(('TWSE','2330'),signal_histories(h,bars[69].date,[event]))
        self.assertEqual(len(signal_histories(h,bars[71].date,[event])[('TPEX','6488')]),72)
        s=Store(':memory:')
        try:
            from dataclasses import asdict
            import_actions(s,[asdict(event)]);self.assertEqual(len(actions(s)),1)
            with self.assertRaises(DataError):import_actions(s,[asdict(replace(event,new_code='1234'))])
        finally:s.close()

    def test_action_source_and_unknown_liquidation_are_rejected(self):
        with self.assertRaises(DataError):self.event(source_url='https://example.com/a')
        with self.assertRaises(DataError):self.event(kind='delisting')
        with self.assertRaises(DataError):self.event(price_factor=float('nan'))

    def test_future_events_do_not_change_prior_fingerprint_or_double_count(self):
        from dataclasses import asdict
        s=Store(':memory:')
        try:
            before=fingerprint(s,'2025-04-02');event=self.event()
            import_actions(s,[asdict(event)])
            self.assertEqual(before,fingerprint(s,'2025-04-02'))
            self.assertNotEqual(before,fingerprint(s,'2025-04-03'))
            with self.assertRaises(DataError):import_actions(s,[asdict(replace(event,event_id='other-id'))])
            self.assertEqual(len(actions(s)),1)
        finally:s.close()

    def test_backfill_request_budget_and_cache(self):
        s=Store(':memory:');calls=[]
        class Client:
            def __init__(self,**kwargs):self.provenance={}
            def daily(self,market,day):
                calls.append((market,day));self.provenance[market]={'url':('https://www.twse.com.tw/exchangeReport/MI_INDEX' if market=='TWSE' else 'https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes')+'?date=x','sha256':'a'*64,'fetched_at':'2025-01-06T18:00:00Z'}
                return [replace(path()[0],market=market,date=day.isoformat(),turnover=100000000,reference=100)]
        study={'data_start':'2025-01-06','as_of':'2025-01-08'};budget={'max_backfill_days':1,'max_requests':2,'backfill_seconds':5}
        try:
            with patch('screener.quality.OfficialClient',Client):
                first=backfill(s,study,budget);second=backfill(s,study,budget)
            self.assertEqual(first['http_requests'],2);self.assertEqual(second['last_completed'],'2025-01-07')
            self.assertEqual(len(calls),4)
            audit=audit_dataset(s,{**study,'holdout_status':'contaminated'})
            self.assertEqual(audit['status'],'blocked');self.assertTrue(any('污染' in text for text in audit['issues']))
        finally:s.close()

    def test_audit_preserves_old_ingestion_error_without_blocking_error_publication(self):
        from screener.quality import main
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'prices.db';s=Store(str(db))
            s.db.execute('CREATE TABLE ingestion_runs(created_at TEXT,payload TEXT)')
            s.db.execute('INSERT INTO ingestion_runs VALUES (?,?)',('2025-01-06',json.dumps({'status':'error','error':'prior official interruption'})))
            s.db.commit();s.close();output=Path(d)/'audit.json'
            with patch('sys.argv',['quality','audit','--db',str(db),'--output',str(output)]):main()
            result=json.loads(output.read_text())
            self.assertEqual(result['status'],'blocked');self.assertEqual(result['backfill']['status'],'error')
