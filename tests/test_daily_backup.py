from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import hashlib,json,sqlite3,tempfile,unittest
from unittest.mock import patch
from screener.backup import save,restore
from screener.daily import produce,promote,paper,approved
from screener.data import Store,DataError
from screener.execution import Execution
from screener.optimizer import code_version
from test_naked import bars

class DailyTests(unittest.TestCase):
    def setUp(self):
        self.s=Store(':memory:');self.cfg=json.loads(Path('naked_k.json').read_text());self.registry=json.loads(Path('strategy_registry.json').read_text())
        b=bars()[100];self.day=b.date
        from datetime import date
        self.s.save_day(date.fromisoformat(b.date),{'TWSE':[b],'TPEX':[__import__('dataclasses').replace(b,market='TPEX',code='6488')]})
    def tearDown(self):self.s.close()
    def test_archived_strategies_do_not_produce_recommendations(self):
        r=produce(self.s,self.cfg,self.registry,{}, {},self.day,True)
        self.assertEqual(r['mode'],'research');self.assertEqual(r['candidates'],[]);self.assertEqual(r['message'],'尚無通過驗證的策略');self.assertFalse(r['orders_enabled'])
    def test_source_error_does_not_show_old_candidates(self):
        r=produce(self.s,self.cfg,self.registry,{}, {},self.day,update_error='official unavailable')
        self.assertEqual(r['status'],'error');self.assertEqual(r['candidates'],[])
    def test_unverified_promotion_and_paper_are_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'registry.json';p.write_text(json.dumps(self.registry));old=p.read_bytes()
            with self.assertRaises(DataError):promote(p,{}, {},{'status':'blocked'},'review')
            self.assertEqual(p.read_bytes(),old)
            self.assertEqual(paper(self.s,self.cfg,self.registry,{}, {},Path(d)/'paper',self.day)['status'],'inactive')
            self.assertFalse(Path(d,'paper').exists())
    def test_tampered_frozen_params_are_not_accepted(self):
        r={'mode':'active','active_strategy':'F','approval_reference':'review','frozen_version':'fake'}
        f={'walk_forward_passed':True,'model_id':'F','frozen_sha256':'fake','parameters':{'max_risk':.9}}
        self.assertIn('雜湊',approved(r,f,{}))

    def test_active_plan_uses_intraday_stop_and_open_risk_cap(self):
        c={'market':'TWSE','code':'2330','date':self.day,'close':100,'stop':94,'target':115}
        view={'candidates':[c],'qualified_count':1,'universe_count':1,'sufficient_history_count':1}
        frozen={'parameters':self.cfg['signal'],'model_id':'F','frozen_sha256':'a'*64}
        with patch('screener.daily.approved',return_value=None),patch('screener.daily.audit_dataset',return_value={'research_ready':True}),patch('screener.daily.screen',return_value=view):
            r=produce(self.s,self.cfg,self.registry,frozen,{},self.day)
        plan=r['candidates'][0]['entry_plan']
        self.assertEqual(r['mode'],'active');self.assertIn('盤中觸及',plan['stop_rule']);self.assertIn('不強迫',plan['target_rule'])
        self.assertLessEqual(plan['maximum_open']*(1+Execution().slippage_rate),94/(1-self.cfg['signal']['max_risk']))

    def test_forward_paper_never_reads_quotes_after_requested_end(self):
        from dataclasses import replace
        from datetime import date
        past=bars()[100];future=replace(past,date='2099-01-01')
        self.s.save_day(date.fromisoformat(future.date),{'TWSE':[future],'TPEX':[replace(future,market='TPEX',code='6488')]})
        registry={'approved_at':self.day+'T18:00:00+08:00'}
        with patch('screener.daily.approved',return_value=None),patch('screener.daily.audit_dataset',return_value={'research_ready':True}):
            with tempfile.TemporaryDirectory() as d:
                result=paper(self.s,self.cfg,registry,{'frozen_sha256':'a'*64},{},Path(d)/'ledger',self.day)
        self.assertEqual(result['status'],'pending');self.assertIn('不足兩日',result['reason'])

    def test_promoted_version_is_isolated_from_research_proposal(self):
        with tempfile.TemporaryDirectory() as d,patch('screener.daily.approved',return_value=None):
            registry=Path(d)/'registry.json';registry.write_text(json.dumps(self.registry))
            frozen={'frozen_sha256':'a'*64,'model_id':'F','parameters':{'minimum_price':20}}
            final={'status':'completed','executed':True}
            promote(registry,frozen,final,{'status':'ready'},'reviewed-change')
            active=json.loads(registry.read_text());p=Path(active['frozen_file']);old=p.read_bytes()
            proposal=Path(d)/'research-proposal.json';proposal.write_text(json.dumps({'model_id':'B'}))
            self.assertEqual(p.read_bytes(),old);self.assertEqual(active['active_strategy'],'F')
            with self.assertRaises(DataError):promote(registry,{**frozen,'parameters':{'minimum_price':99}},final,{'status':'ready'},'new-review')
            self.assertEqual(p.read_bytes(),old)

class BackupTests(unittest.TestCase):
    def test_chunks_verified_and_corruption_keeps_previous_database(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'source.db';db=sqlite3.connect(source);db.execute('CREATE TABLE sample(value BLOB)')
            import random
            payload=random.Random(7).randbytes(20000);db.execute('INSERT INTO sample VALUES (?)',(payload,));db.commit();db.close()
            backup=Path(d)/'backup';manifest=save(str(source),backup,1024);self.assertGreater(len(manifest['parts']),1)
            target=Path(d)/'target.db';restore(backup,target);before=target.read_bytes()
            db=sqlite3.connect(target);self.assertEqual(db.execute('SELECT value FROM sample').fetchone()[0],payload);db.close()
            first=backup/manifest['parts'][0]['name'];first.write_bytes(b'broken')
            with self.assertRaisesRegex(ValueError,'校驗'):restore(backup,target)
            self.assertEqual(target.read_bytes(),before)
    def test_backup_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            b=Path(d);(b/'manifest.json').write_text(json.dumps({'schema_version':1,'format':'sqlite-gzip-split','parts':[{'name':'../private','sha256':'x','bytes':1}]}))
            with self.assertRaises(ValueError):restore(b,b/'data.db')
