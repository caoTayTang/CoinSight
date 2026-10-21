#!/usr/bin/env bash
# Pull-based deploy for the home server: bring the stack up to origin/main once CI has passed for that commit.
# The repository is public, so nothing triggers this from GitHub and no GitHub runner executes code here: the
# server only ever runs code that was merged to main and passed CI. Run it from cron/launchd every few minutes.
#
#   deploy/home/deploy.sh            # deploy if origin/main moved and its CI passed
#   deploy/home/deploy.sh --force    # redeploy the current checkout (first install, after editing .env)
set -euo pipefail
cd "$(dirname "$0")/../.."
LOCK=/tmp/coinsight-deploy.lock
mkdir "$LOCK" 2>/dev/null || exit 0          # another deploy is running
trap 'rmdir "$LOCK"' EXIT
log() { echo "$(date -u +%FT%TZ) $*" | tee -a data/deploy.log; }

git fetch -q origin main
target=$(git rev-parse origin/main)
if [ "$target" = "$(git rev-parse HEAD)" ] && [ "${1:-}" != "--force" ]; then exit 0; fi

if [ "${1:-}" != "--force" ]; then
  # Every check run on the commit must have finished successfully (skipped counts as success).
  state=$(gh api "repos/{owner}/{repo}/commits/$target/check-runs" --jq \
    '[.check_runs[] | select(.name != "deploy") | .conclusion] |
     if length == 0 or any(. == null) then "pending" elif all(. == "success" or . == "skipped") then "success" else "failure" end')
  if [ "$state" != success ]; then log "skip $target: CI $state"; exit 0; fi
  git merge --ff-only -q origin/main
fi
log "deploying $(git rev-parse --short HEAD)"

CORE=(docker compose -f docker-compose.yml -f deploy/home/compose.restart.yml)
"${CORE[@]}" up -d --build                                               # warehouse, Kafka, Spark, live, API, UI
"${CORE[@]}" --profile airflow up -d --build airflow                     # daily batch ETL
docker compose -p coinsight-agents -f compose.agents.yml up -d --build   # forecast, anomaly, prediction ledger
docker compose --env-file .env -f warehouse_agents/compose.yml up -d --build   # Trade/SRE agents + gateway

for url in http://127.0.0.1:8000/health http://127.0.0.1:3000/ http://127.0.0.1:8020/health; do
  curl -fsS --retry 20 --retry-all-errors --retry-delay 3 -o /dev/null "$url" || { log "FAILED health $url"; exit 1; }
done
log "deployed $(git rev-parse --short HEAD)"
