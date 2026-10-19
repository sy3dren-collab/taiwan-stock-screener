#!/usr/bin/env bash
set -euo pipefail
if [ "${GITHUB_ACTIONS:-}" != 'true' ]; then
  echo 'This helper operates only on the disposable Actions .history checkout.' >&2
  exit 1
fi
python -m screener.backup save --directory .history/backup
for folder in experiments paper; do
  if [ -d ".state/$folder" ]; then cp -R ".state/$folder" .history/; fi
done
for report in results research data-quality final-test paper; do
  if [ -f "site/$report.json" ]; then cp "site/$report.json" ".history/latest-$report.json"; fi
done
cd .history
git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
git rm --ignore-unmatch prices.sqlite3 prices.sqlite3.gz
git add backup
for folder in experiments paper; do
  if [ -d "$folder" ]; then git add "$folder"; fi
done
for report in results research data-quality final-test paper; do
  if [ -f "latest-$report.json" ]; then git add "latest-$report.json"; fi
done
if ! git diff --cached --quiet; then
  git commit -m 'data: preserve official evidence and bounded research state'
  git push origin HEAD:research-data
fi
