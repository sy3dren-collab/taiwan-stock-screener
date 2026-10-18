from argparse import Namespace
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from screener.__main__ import run
from screener.data import DataError, Store
from test_data import DAY, twse, tpex
from screener.data import parse_report


class PipelineTests(unittest.TestCase):
    def args(self, root, command='update'):
        config=root/'strategy.json'; config.write_text('{}')
        return Namespace(command=command,db=str(root/'prices.sqlite3'),output=str(root/'results.json'),config=str(config),end=DAY,lookback_days=180,delay=0)

    def test_source_failure_produces_error_json_and_nonzero_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);args=self.args(root)
            with patch('screener.__main__.OfficialClient') as factory:
                factory.return_value.daily.side_effect=DataError('official HTTP 403')
                self.assertEqual(run(args),1)
            result=json.loads((root/'results.json').read_text())
            self.assertEqual(result['status'],'error')
            self.assertEqual(result['candidates'],[])
            self.assertIn('403',result['errors'][0])
            self.assertFalse((root/'results.json.tmp').exists())

    def test_offline_screen_retains_honest_insufficient_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);args=self.args(root,'screen')
            store=Store(args.db)
            store.save_day(DAY,{'TWSE':parse_report('TWSE',DAY,twse()),'TPEX':parse_report('TPEX',DAY,tpex())})
            store.close()
            self.assertEqual(run(args),0)
            result=json.loads((root/'results.json').read_text())
            self.assertEqual(result['status'],'ok')
            self.assertEqual(result['universe_count'],2)
            self.assertEqual(result['sufficient_history_count'],0)
            self.assertEqual(result['candidates'],[])
            self.assertTrue(result['shortfall'])
            self.assertTrue(any('離線' in w for w in result['warnings']))

    def test_invalid_config_stale_history_and_missing_db_are_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);args=self.args(root,'screen')
            self.assertEqual(run(args),1)
            (root/'strategy.json').write_text('{"fast_ma":1000}')
            self.assertEqual(run(args),1)
            self.assertEqual(json.loads((root/'results.json').read_text())['status'],'error')
            (root/'strategy.json').write_text('{}')
            store=Store(args.db);store.save_day(DAY,{'TWSE':parse_report('TWSE',DAY,twse()),'TPEX':parse_report('TPEX',DAY,tpex())});store.close()
            args.end=date(2025,2,1)
            self.assertEqual(run(args),1)
            self.assertIn('超過 7 天',json.loads((root/'results.json').read_text())['errors'][0])
