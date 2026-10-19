#!/usr/bin/env bash
set -euo pipefail
if [ "${GITHUB_ACTIONS:-}" != 'true' ]; then
  echo 'This helper operates only on the disposable Actions .history checkout.' >&2
  exit 1
fi
mkdir -p .state
cd .history
remote_ref=$(git ls-remote origin refs/heads/research-data)
if [ -n "$remote_ref" ]; then
  git fetch origin refs/heads/research-data
  git checkout -B research-data FETCH_HEAD
else
  fallback=$(git ls-remote origin refs/heads/market-data)
  if [ -n "$fallback" ]; then
    git fetch origin refs/heads/market-data
    git checkout -B research-data FETCH_HEAD
  else
    git checkout --orphan research-data
    git rm -rf --ignore-unmatch .
  fi
fi
cd ..
if [ -f .history/backup/manifest.json ]; then
  python -m screener.backup restore --directory .history/backup
elif [ -f .history/prices.sqlite3.gz ]; then
  gzip -dc .history/prices.sqlite3.gz > .state/prices.sqlite3
elif [ -f .history/prices.sqlite3 ]; then
  cp .history/prices.sqlite3 .state/prices.sqlite3
fi
for folder in experiments paper; do
  if [ -d ".history/$folder" ]; then cp -R ".history/$folder" .state/; fi
done
for report in research data-quality final-test; do
  if [ -f ".history/latest-$report.json" ]; then cp ".history/latest-$report.json" "site/$report.json"; fi
done
