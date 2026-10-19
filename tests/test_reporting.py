from pathlib import Path
import os
import json,tempfile,unittest
from unittest.mock import patch

from screener.reporting import record_run,export_history
from screener.optimizer import main


class ReportingTests(unittest.TestCase):
    def blocked(self):return {'status':'blocked','research_model_id':'F','experiments':[],'stop_reason':'data_quality','data_quality':{'issues':['missing real turnover'],'data_sha256':'test-only'},'version':{'git_commit':'test-only'}}
    def test_every_blocked_or_failed_attempt_is_persisted_without_fabricated_zero_return(self):
        with tempfile.TemporaryDirectory() as d:
            state,site,summary=Path(d)/'state',Path(d)/'site',Path(d)/'summary.md'
            first=record_run(self.blocked(),'research',d,state,site,summary)
            second=record_run({**self.blocked(),'status':'error','run_error':'quote failed'},'research',d,state,site,summary)
            history=json.loads((site/'research-history.json').read_text())
            self.assertEqual(history['total_runs'],2);self.assertEqual(history['runs'][0]['run_id'],second['run_id'])
            self.assertNotEqual(first['run_id'],second['run_id']);self.assertEqual(first['trials'],[])
            self.assertTrue((state/(first['run_id']+'.json')).exists());self.assertIn('quote failed',summary.read_text())
            self.assertIn('不是',summary.read_text());self.assertNotIn('0.00%',summary.read_text())
            self.assertEqual(len((state/'ledger.jsonl').read_text().splitlines()),2)
            self.assertTrue((site/history['runs'][0]['download_url']).exists())
    def test_all_losing_and_winning_trades_are_in_report_and_baseline_is_distinct(self):
        with tempfile.TemporaryDirectory() as d:
            record={'experiment_id':'test-F-0','iteration':0,'status':'completed','reason':'fixed baseline','retained':False,
                    'results':{'validation':[{'metrics':{'net_return':-.01,'max_drawdown':.02,'total_costs':25},'closed_trades':[{'net_pnl':100},{'net_pnl':-200}]}]}}
            Path(d,'test-F-0.json').write_text(json.dumps(record))
            result={**self.blocked(),'status':'completed','experiments':[record]}
            run=record_run(result,'research',d,Path(d)/'state',Path(d)/'site')
            t=run['trials'][0];self.assertEqual(t['closed_count'],2);self.assertEqual(t['win_rate'],.5)
            self.assertEqual(t['expectancy'],-50);self.assertEqual(t['profit_factor'],.5);self.assertEqual(t['total_validation_costs'],25)
            self.assertFalse(t['retained']);self.assertEqual(t['mean_validation_return'],-.01)
            snapshot=json.loads(Path(d,'state',run['run_id']+'.json').read_text())
            self.assertEqual(len(snapshot['trial_reports'][0]['results']['validation'][0]['closed_trades']),2)
    def test_export_restores_history_and_never_creates_new_runs(self):
        with tempfile.TemporaryDirectory() as d:
            state,site=Path(d)/'state',Path(d)/'site'
            env_summary=Path(d)/'ci-summary.md'
            with patch.dict(os.environ,{'GITHUB_STEP_SUMMARY':str(env_summary)}):record_run(self.blocked(),'research',d,state,site)
            self.assertFalse(env_summary.exists())
            before=(state/'ledger.jsonl').read_bytes()
            export_history(state,Path(d)/'restored')
            self.assertEqual(before,(state/'ledger.jsonl').read_bytes())
            self.assertTrue(Path(d,'restored/latest-backtest.md').exists())
    def test_cli_failure_still_writes_report_in_selected_output_directory(self):
        with tempfile.TemporaryDirectory() as d:
            cfg=Path(d)/'bad.json';cfg.write_text('invalid-json');out=Path(d)/'public/research.json';state=Path(d)/'runs'
            with patch.dict(os.environ,{'GITHUB_STEP_SUMMARY':''}),patch('sys.argv',['optimizer','research','--config',str(cfg),'--output',str(out),'--runs',str(state)]):
                with self.assertRaises(SystemExit) as raised:main()
            self.assertEqual(raised.exception.code,1);result=json.loads(out.read_text());self.assertEqual(result['status'],'error')
            history=json.loads((out.parent/'research-history.json').read_text());self.assertEqual(history['total_runs'],1)
            self.assertEqual(history['runs'][0]['status'],'error');self.assertTrue((state/'ledger.jsonl').exists())
