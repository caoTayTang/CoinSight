---
name: missing-candles
description: Finds missing, late or duplicated hourly candles for BTC, ETH or SOL and traces the gap to a batch. Use when the user reports gaps, holes in a chart, stale or late data, "thiếu giờ dữ liệu", or asks whether hourly data is complete.
---

# Missing-candle check

## What the tools return

`warehouse_coverage(symbol, hours)` compares the closed hours in the window with rows in `dw.fact_ohlcv_hourly`.

| Field | Meaning |
|---|---|
| `expected_hours` | Closed hours in the window. The current, still-open hour is never counted. |
| `observed_hours` | Hours with at least one row. |
| `missing_hours` | `expected_hours - observed_hours`. |
| `last_observed_open` | Newest hour present. If it is not the latest closed hour, ingestion stopped after it. |
| `duplicated_grain_hours` | Hours with more than one row. The grain is source/symbol/interval/open_time, so any value above 0 is a loader defect, not a gap. |

Coverage returns counts, not the list of missing hours. Name only `last_observed_open`; never list individual missing hours.

`warehouse_status` groups `meta.etl_batch` from the last 7 days by pipeline and status (`batches`, `latest_started`, `latest_finished`). `warehouse_lineage(symbol)` gives the 5 newest hourly facts with `batch_id`, `source_file` and `sha256`.

## Workflow

If the user asks you to re-run, backfill or fix anything, open the answer by saying you can't: you are read-only and an operator must run it. Then investigate and report as below.

Call steps 1 to 3 together in one step. The step budget is small.

```
- [ ] 1. warehouse_coverage for the asset asked about. Window 48 unless the user gave one (1 to 168).
- [ ] 2. warehouse_coverage for the other two assets, same window.
- [ ] 3. warehouse_status, and warehouse_lineage for the affected asset.
- [ ] 4. Only if a batch failed or none finished recently: airflow_status with dag_id coinsight_warehouse_daily.
```

## Reading the result

| Observation | Reading | Operator's next step |
|---|---|---|
| `missing_hours` 0 and `duplicated_grain_hours` 0 | Complete. Stop there. | None |
| `missing_hours` > 0, `last_observed_open` is the latest closed hour | Holes inside the window; ingestion is running | Find the failed batch in `warehouse_status`, re-run the warehouse DAG for those dates |
| `last_observed_open` older than the latest closed hour | Ingestion stopped after that hour | Check the latest DAG run and the source archive for the next day |
| Same gap on all three assets | Pipeline-wide: scheduler, source or loader | Airflow DAG runs first |
| Gap on one asset only | That asset's archive or batch | `warehouse_lineage` for that asset |
| `duplicated_grain_hours` > 0 | Uniqueness defect in the load | Check `warehouse_reconciliation` for that batch |

Recovery is a re-run of the batch for the affected dates. The loader upserts on the grain, so a re-run doesn't create duplicates. You recommend it; you never run it or write SQL.

## Report

```markdown
**<asset> is missing <missing_hours> of the last <expected_hours> hours.**

| Asset | Missing | Duplicated | Last observed (UTC) |
|---|---:|---:|---|
| <asset> | <missing_hours> | <duplicated_grain_hours> | <last_observed_open> |

Where it stopped: <pipeline> <status>, latest finished <latest_finished>; newest fact from batch <batch_id>.
Next step: <one operator action from the table>.

[skill:missing-candles]
```

Include every asset with a gap, including ones the user didn't name. If Airflow was unavailable, write "Airflow not checked" instead of guessing its state.

## Gotchas

- Missing hours are a data-availability problem, not a market event.
- A running container doesn't prove data is fresh. An unreachable Airflow API doesn't prove the scheduler stopped.
- Don't offer example windows or counts ("for example the last 24 hours"); use the window you queried.

Every figure in the answer comes from a tool result in this conversation. Placeholders in <angle brackets> show where a tool value goes; never fill them with example or estimated numbers, and say "not checked" instead.
