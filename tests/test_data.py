"""Fabricated test fixtures only; never exported as website market prices."""
from datetime import date
import sqlite3
import unittest
from unittest.mock import patch
from urllib.error import URLError

from screener.data import Bar, DataError, OfficialClient, Store, parse_report
from screener.__main__ import update

DAY = date(2025, 1, 6)


def twse(**updates):
    value = {'stat': 'OK', 'date': '20250106', 'fields9': ['證券代號','證券名稱','成交股數','開盤價','最高價','最低價','收盤價'],
             'data9': [['2330','測試股票','1,234,567','100','105','98','104'], ['0050','測試 ETF','100','1','1','1','1']]}
    value.update(updates)
    return value


def tpex():
    return {'stat':'ok', 'date':'114/01/06', 'tables':[{'fields':['代號','名稱','收盤','漲跌','開盤','最高','最低','成交仟股'],
             'data':[['6488','測試上櫃','102','+2','100','103','99','1,200.5']]}]}


class ParserTests(unittest.TestCase):
    def test_twse_ohlcv_and_share_units(self):
        bars = parse_report('TWSE',DAY,twse())
        self.assertEqual(len(bars),1)
        self.assertEqual(bars[0].volume,1234567)
        self.assertEqual((bars[0].open,bars[0].high,bars[0].low,bars[0].close),(100,105,98,104))

    def test_tpex_roc_date_and_thousand_share_units(self):
        bar = parse_report('TPEX',DAY,tpex())[0]
        self.assertEqual(bar.date,'2025-01-06')
        self.assertEqual(bar.volume,1200500)
        self.assertEqual(bar.close,102)

    def test_modern_twse_table_shape(self):
        report = twse()
        report['tables']=[{'fields':report.pop('fields9'),'data':report.pop('data9')}]
        self.assertEqual(parse_report('TWSE',DAY,report)[0].code,'2330')

    def test_explicit_holiday_only(self):
        self.assertEqual(parse_report('TWSE',DAY,{'stat':'很抱歉，沒有符合條件的資料!'}),[])
        for payload in ({}, {'stat':'too many requests'}, {'stat':'ok','tables':[]}):
            with self.assertRaises(DataError): parse_report('TWSE',DAY,payload)

    def test_wrong_date_rejected(self):
        with self.assertRaises(DataError): parse_report('TWSE',DAY,twse(date='20250107'))

    def test_invalid_price_volume_and_ohlc_rejected(self):
        for column,value in ((2,'-1'),(2,'1.5'),(3,'NaN'),(3,'1e999'),(4,'99'),(5,'106')):
            report=twse(); report['data9'][0][column]=value
            with self.assertRaises(DataError): parse_report('TWSE',DAY,report)

    def test_duplicate_rejected(self):
        report=twse();report['data9'].append(report['data9'][0])
        with self.assertRaises(DataError):parse_report('TWSE',DAY,report)

    def test_no_simulated_fallback_on_network_failure(self):
        with patch('screener.data.urlopen',side_effect=URLError('blocked')), patch('screener.data.time.sleep'):
            with self.assertRaisesRegex(DataError,'官方資料取得失敗'):
                OfficialClient(delay=0,retries=1).daily('TWSE',DAY)


class StoreTests(unittest.TestCase):
    def setUp(self): self.store=Store(':memory:')
    def tearDown(self): self.store.close()
    def reports(self):return {'TWSE':parse_report('TWSE',DAY,twse()),'TPEX':parse_report('TPEX',DAY,tpex())}

    def test_idempotent_upsert_and_correction(self):
        reports=self.reports();self.store.save_day(DAY,reports);self.store.save_day(DAY,reports)
        self.assertEqual(self.store.db.execute('select count(*) from bars').fetchone()[0],2)
        self.assertEqual(self.store.last_checked(),DAY)
        changed=twse();changed['data9'][0][-1]='103'
        reports['TWSE']=parse_report('TWSE',DAY,changed);self.store.save_day(DAY,reports)
        self.assertEqual(self.store.histories(DAY.isoformat())[('TWSE','2330')][0].close,103)

    def test_sql_failure_rolls_back_day_replacement(self):
        reports=self.reports()
        self.store.save_day(DAY,reports)
        reports['TWSE']=reports['TWSE']*2
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.save_day(DAY,reports)
        self.assertEqual(self.store.db.execute('select count(*) from bars').fetchone()[0],2)
        self.assertEqual(self.store.histories(DAY.isoformat())[('TWSE','2330')][0].close,104)

    def test_partial_day_is_not_persisted(self):
        with self.assertRaises(DataError): self.store.save_day(DAY,{'TWSE':self.reports()['TWSE']})
        with self.assertRaises(DataError): self.store.save_day(DAY,{'TWSE':[],'TPEX':self.reports()['TPEX']})
        self.assertIsNone(self.store.last_checked())

    def test_point_in_time_never_returns_future(self):
        self.store.save_day(DAY,self.reports())
        self.assertEqual(self.store.histories('2025-01-05'),{})

    def test_incremental_fetch_rechecks_recent_days(self):
        self.store.save_day(DAY,self.reports())
        calls=[]
        class Client:
            def daily(self,market,day):calls.append((market,day));return []
        update(self.store,Client(),date(2025,1,8),180)
        self.assertEqual(min(d for _,d in calls),date(2024,12,30))
        self.assertEqual(max(d for _,d in calls),date(2025,1,8))
        self.assertEqual(len(calls),16)

    def test_ensure_history_skips_only_officially_checked_dates(self):
        self.store.save_day(DAY,self.reports())
        calls=[]
        class Client:
            def daily(self,market,day):calls.append((market,day));return []
        update(self.store,Client(),date(2025,1,7),180,start=DAY,missing_only=True)
        self.assertEqual(calls,[('TWSE',date(2025,1,7)),('TPEX',date(2025,1,7))])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM bars').fetchone()[0],2)

    def test_failed_second_market_does_not_mark_complete(self):
        class Client:
            def daily(_,market,day):
                if market=='TPEX': raise DataError('failed')
                return self.reports()['TWSE']
        with self.assertRaises(DataError): update(self.store,Client(),DAY,0)
        self.assertIsNone(self.store.last_checked())
