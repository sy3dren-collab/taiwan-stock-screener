import unittest
from unittest.mock import Mock
from screener.fast import qualifies, run


def result(profit=0, trades=0):
    return {'status': 'completed', 'strategy': {
        'closed_trades': [{}] * trades, 'metrics': {'net_return': profit}}}


class FastTests(unittest.TestCase):
    def test_net_profit_and_sample_required(self):
        self.assertFalse(qualifies(result(.1, 0), 5))
        self.assertFalse(qualifies(result(-.01, 10), 5))
        self.assertFalse(qualifies(result(0, 10), 5))
        self.assertTrue(qualifies(result(.01, 5), 5))

    def execute(self, outcomes):
        runner = Mock(side_effect=outcomes)
        report = run(None, {'start': '2025-10-17', 'end': '2026-10-16'},
                     {'short_start': '2026-07-17', 'minimum_trades': 5,
                      'max_candidates': 3, 'short_budget_seconds': 180,
                      'long_budget_seconds': 120}, runner, Mock(return_value={}))
        return report, runner

    def test_no_annual_when_all_fail(self):
        report, runner = self.execute([result(), result(-.01, 10), result(.1, 2)])
        self.assertEqual(runner.call_count, 3)
        self.assertIsNone(report['long_run'])

    def test_only_best_gets_one_annual_run(self):
        report, runner = self.execute([result(.01, 5), result(.03, 5), result(), result(-.1, 20)])
        self.assertEqual(runner.call_count, 4)
        self.assertEqual(report['long_run']['candidate'], 'wider-base')
        self.assertFalse(report['promotion_allowed'])
        self.assertEqual(runner.call_args.kwargs['seconds'], 120)
