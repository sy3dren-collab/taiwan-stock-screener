#!/usr/bin/env bash
set -euo pipefail
if [ "${GITHUB_ACTIONS:-}" != 'true' ]; then
  echo 'This helper operates only on the disposable Actions .history checkout.' >&2
  exit 1
fi
if [ "${REPORTS_ONLY:-false}" != true ] || [ -f .state/research-db-changed ]; then
  python -m screener.backup save --directory .history/backup
fi
for folder in experiments paper runs; do
  if [ -d ".state/$folder" ]; then cp -R ".state/$folder" .history/; fi
done
for report in results research data-quality final-test paper annual-backtest annual-backfill annual-events annual-wider-range fast-backtest watchlist-audit; do
  if [ -f "site/$report.json" ]; then cp "site/$report.json" ".history/latest-$report.json"; fi
done
if [ -d site/fast-runs ]; then mkdir -p .history/fast-runs; cp -n site/fast-runs/*.json .history/fast-runs/; fi
if [ -d site/watchlist-audits ]; then mkdir -p .history/watchlist-audits; cp -n site/watchlist-audits/*.json .history/watchlist-audits/; fi
cd .history
git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
git rm --ignore-unmatch prices.sqlite3 prices.sqlite3.gz
git add backup
if [ -d watchlist-audits ]; then git add watchlist-audits; fi
if [ -d fast-runs ]; then git add fast-runs; fi
for folder in experiments paper runs; do
  if [ -d "$folder" ]; then git add "$folder"; fi
done
for report in results research data-quality final-test paper annual-backtest annual-backfill annual-events annual-wider-range fast-backtest watchlist-audit; do
  if [ -f "latest-$report.json" ]; then git add "latest-$report.json"; fi
done
if ! git diff --cached --quiet; then
  git commit -m 'data: preserve official evidence and bounded research state'
  git push origin HEAD:research-data
fi
