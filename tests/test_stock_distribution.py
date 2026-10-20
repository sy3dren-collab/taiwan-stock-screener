from dataclasses import replace
import json
from pathlib import Path
import unittest

from screener.data import Store
from screener.distributions import event_tables,import_verified_details
from screener.quality import CorporateAction,actions
from screener.fast import qualifies
from test_naked import bars,execute


class StockDistributionTests(unittest.TestCase):
    def test_original_official_detail_has_cash_and_stock_terms_and_is_idempotent(self):
        store=Store(':memory:')
        try:
            event_tables(store)
            row={'market':'TWSE','code':'2801','date':'2026-08-05','kind':'權息',
                 'before':25.2,'after':23.8,'reference':23.8,'cash':None,'supported':False}
            store.db.execute('INSERT INTO distribution_rows VALUES (?,?,?,?,?)',
                ('TWSE','2801','2026-08-05',json.dumps(row),'test'))
            self.assertEqual(import_verified_details(store),1)
            action=actions(store)[0]
            self.assertEqual(action.share_factor,1.025)
            self.assertEqual(action.cash_per_share,.8)
            self.assertEqual(import_verified_details(store),0)
        finally:store.close()

    def test_undelivered_stock_is_not_sold_or_reinvested_and_cannot_pass_gate(self):
        seq=bars()
        for i in range(103,len(seq)):
            seq[i]=replace(seq[i],open=96.59,close=96.59,low=96.09,high=97.09,reference=96.59)
        action=CorporateAction('stock-cash','TWSE','2330',seq[103].date,seq[103].date,
            'distribution','https://www.twse.com.tw/event',price_factor=96.59/100,
            share_factor=1.025,cash_per_share=1,reference_price=96.59)
        report=execute(seq,events=[action])
        trade=report['closed_trades'][0]
        stock=[r for r in report['receivables'] if r.get('stock_quantity')][0]
        self.assertEqual(stock['stock_quantity'],round(trade['quantity']*.025))
        self.assertFalse(stock['paid'])
        self.assertIsNone(stock['payable_date'])
        self.assertGreater(stock['estimated_value'],0)
        self.assertEqual(report['unsettled_stock_dividends'],1)
        report['closed_trades']*=5
        report['metrics']['net_return']=.1
        self.assertFalse(qualifies({'status':'completed','strategy':report},5))
