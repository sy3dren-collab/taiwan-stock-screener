import json,tempfile,unittest
from pathlib import Path
from scripts.preserve_quote_error import preserve


class PublicationTests(unittest.TestCase):
    def test_offline_research_preserves_source_failure_and_removes_active_claims(self):
        with tempfile.TemporaryDirectory() as d:
            old,new=Path(d)/'previous.json',Path(d)/'results.json'
            old.write_text(json.dumps({'status':'error','errors':['official transfer failed'],'generated_at':'2026-10-19T20:00:00+08:00'}))
            new.write_text(json.dumps({'status':'ok','mode':'active','candidates':[{'code':'test-only'}],'strategies':{'F':{}},'active_strategy':'F'}))
            self.assertTrue(preserve(old,new));r=json.loads(new.read_text())
            self.assertEqual(r['status'],'error');self.assertEqual(r['candidates'],[]);self.assertEqual(r['strategies'],{})
            self.assertIsNone(r['active_strategy']);self.assertEqual(r['errors'],['official transfer failed'])
            self.assertEqual(r['source_error_at'],'2026-10-19T20:00:00+08:00')
            self.assertFalse(json.loads(Path(d,'active-performance.json').read_text())['executed'])
    def test_successful_previous_update_does_not_replace_current_output(self):
        with tempfile.TemporaryDirectory() as d:
            old,new=Path(d)/'previous.json',Path(d)/'results.json'
            old.write_text(json.dumps({'status':'ok'}));new.write_text(json.dumps({'status':'ok','mode':'research'}));before=new.read_bytes()
            self.assertFalse(preserve(old,new));self.assertEqual(new.read_bytes(),before)
    def test_missing_previous_update_does_not_fabricate_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            new=Path(d)/'results.json';new.write_text(json.dumps({'status':'ok'}));before=new.read_bytes()
            self.assertFalse(preserve(Path(d)/'missing.json',new));self.assertEqual(new.read_bytes(),before)
