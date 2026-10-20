"""Bounded quarterly screening, followed by at most one retrospective annual check."""
import argparse
from dataclasses import replace
from datetime import date, datetime, timezone
import json
from pathlib import Path
import time

from .annual import audit_year, run_year
from .data import Store
from .naked import NakedParameters
from .__main__ import write_json

# Fixed before running; preserve every failure and never search until profitable.
CANDIDATES = [
    ('baseline', {}),
    ('wider-base', {'range_width': .30, 'range_drift_max': .12}),
    ('flexible-retest', {'range_width': .30, 'range_drift_max': .12,
                         'extension_max': .06, 'support_tolerance': .03,
                         'pullback_volume_max': .95}),
]


def qualifies(result, minimum):
    report = result.get('strategy', {})
    return (result.get('status') == 'completed'
            and len(report.get('closed_trades', [])) >= minimum
            and report.get('metrics', {}).get('net_return', 0) > 0)


def run(store, annual, config, runner=run_year, auditor=audit_year):
    began = time.monotonic()
    quality = auditor(store, annual)  # Audit/fingerprint once, no downloads per candidate.
    short = dict(annual, start=config['short_start'])
    if not annual['start'] <= short['start'] < annual['end']:
        raise ValueError('短期日期必須在長期區間內')
    if not 1 <= config['max_candidates'] <= len(CANDIDATES):
        raise ValueError('候選版本上限為三個')
    if config['minimum_trades'] < 5:
        raise ValueError('初篩至少需要五筆已平倉交易')
    if not 0 < config['short_budget_seconds'] <= 300 or not 0 < config['long_budget_seconds'] <= 180:
        raise ValueError('初篩最多300秒、長期最多180秒')
    if (date.fromisoformat(annual['end']) - date.fromisoformat(short['start'])).days > 93:
        raise ValueError('初篩區間不得超過三個月（93天）')
    base = NakedParameters(**json.loads(Path('naked_k.json').read_text())['signal'])
    output = {'generated_at': datetime.now(timezone.utc).isoformat(),
              'classification': 'retrospective_diagnostic', 'promotion_allowed': False,
              'active_strategy': None, 'config': config, 'short_runs': [],
              'long_run': None, 'long_gate': '未通過短期正收益與最低交易數門檻，未執行一年回測',
              'limitations': ['短期篩選可能過度擬合；一年包含這三個月，並非獨立樣本外驗證。',
                              '費用、交易稅、滑價沿用原設定；期末預留20交易日平倉，零交易不合格。']}
    deadline = time.monotonic() + config['short_budget_seconds']
    for name, changes in CANDIDATES[:config['max_candidates']]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            result = runner(store, short, parameters=replace(base, **changes),
                            seconds=remaining, quality=quality)
        except Exception as exc:
            result = {'status': 'error', 'run_error': str(exc)}
        result.update(candidate=name, changed_parameters=changes)
        result['short_gate_passed'] = qualifies(result, config['minimum_trades'])
        output['short_runs'].append(result)
        if runner is run_year:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            write_json(Path('site/fast-runs') / (stamp + '-' + name + '.json'), result)
            print(json.dumps({'candidate': name, 'status': result['status'],
                  'trades': len(result.get('strategy', {}).get('closed_trades', [])),
                  'net_return': result.get('strategy', {}).get('metrics', {}).get('net_return')}, ensure_ascii=False), flush=True)
    passed = [r for r in output['short_runs'] if r['short_gate_passed']]
    if passed:
        winner = max(passed, key=lambda r: r['strategy']['metrics']['net_return'])
        output['long_gate'] = '短期通過；只對最佳淨報酬版本執行一次一年回溯驗證'
        output['long_run'] = runner(store, annual,
            parameters=replace(base, **winner['changed_parameters']),
            seconds=config['long_budget_seconds'], quality=quality)
        output['long_run']['candidate'] = winner['candidate']
    output['elapsed_seconds'] = round(time.monotonic() - began, 3)
    results = output['short_runs'] + ([output['long_run']] if output['long_run'] else [])
    output['status'] = 'completed' if results and all(r['status'] == 'completed' for r in results) else 'blocked'
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='.state/prices.sqlite3')
    args = parser.parse_args()
    store = Store(args.db)
    try:
        output = run(store, json.loads(Path('annual_research.json').read_text()),
                     json.loads(Path('fast_research.json').read_text()))
    finally:
        store.close()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    write_json(Path('site/fast-backtest.json'), output)
    write_json(Path('site/fast-runs') / (stamp + '.json'), output)
    for result in output['short_runs']:
        print(json.dumps({'candidate': result['candidate'], 'status': result['status'],
              'trades': len(result.get('strategy', {}).get('closed_trades', [])),
              'metrics': result.get('strategy', {}).get('metrics'),
              'elapsed_seconds': result.get('elapsed_seconds')}, ensure_ascii=False), flush=True)
    print(output['long_gate'], flush=True)
    if output['status'] != 'completed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
