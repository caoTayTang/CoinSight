---
name: missing-candles
description: Missing, stale or late hourly candles in the warehouse (gaps, "thiếu giờ dữ liệu", charts with holes). Use to find which hours are missing, why, and what an operator should check.
---
# Missing or stale candles

## Steps
1. `warehouse_coverage` with the asset and window (24, 48 or 168 hours). Read `missing_hours`, `last_observed_open`
   and `duplicated_grain_hours`. The current, still-open hour is never counted as missing.
2. `warehouse_status` for recent batch states, then `warehouse_lineage` to find the archive and batch behind the
   last good hour.
3. `airflow_status` for the DAG runs, if Airflow is configured.
4. If the user asked about one asset, still check the others in the same coverage result and report any gap.

## How to report
- Lead with the count from `warehouse_coverage`: "<missing> of the last <window> hours are missing for <asset>", then list the hours (UTC).
- Then the likely point of failure, phrased as an observation: "the last successful batch was <batch id> at <time>".
- Then the operator's next step.

## Boundaries
- Missing hours are a data-availability problem, not a market anomaly.
- A running container doesn't prove data is fresh; an unreachable Airflow doesn't prove the scheduler stopped.
- Recovery keeps the asset/source/interval/open_time grain and uses the idempotent loader. You only recommend it;
  you don't run backfills or write SQL.

Every figure in the answer comes from a tool result in this conversation. Placeholders in <angle brackets> show
where a tool value goes; never fill them with example or estimated numbers, and say "not checked" instead.
