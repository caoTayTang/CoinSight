---
name: warehouse-reconciliation
description: Localises warehouse accounting errors, mart/fact mismatches and failed data quality checks to a batch, a check or a stale mart. Use when rows don't add up, mart totals differ from facts, a quality check failed, or the user asks for "đối soát".
---

# Warehouse reconciliation

## What the tools return

`warehouse_reconciliation`: the 20 newest rows of `meta.warehouse_load_report`, one per batch and symbol and interval.

| Field | Meaning |
|---|---|
| `staging_rows` | Rows read from the archive into staging |
| `rejected_rows` | Rows that failed an error-severity rule |
| `duplicate_rows` | Valid rows dropped as duplicates of the grain |
| `accepted_rows` | Rows passed to the upsert |
| `changed_rows` | Facts actually inserted or updated. Lower than accepted is normal on a re-run. |
| `accounting_delta` | `staging - (rejected + duplicate + accepted)`. Must be 0. |
| `load_status`, `finished_at` | The batch's final state |

`warehouse_mart_parity`: per source and symbol, `fact_candles` vs `mart_candles` and `fact_volume` vs `mart_volume` (quote volume, USDT), the differences `candle_gap` and `volume_gap` (fact minus mart, already computed), and `aggregates_match`. The mart `mart.mv_hourly_activity` is refreshed at the end of each load batch.

`warehouse_quality`: the 30 newest checks of the last 7 days, with `batch_id`, `check_name`, `severity`, `failed_rows`, `passed`.

| Severity | Checks | Effect |
|---|---|---|
| `error` | `not_null`, `positive_price`, `ohlc_consistency`, `non_negative_volume`, `interval_alignment`, `known_source`, `date_in_calendar` | Failing rows are rejected |
| `warning` | `duplicate_grain`, `zero_volume`, `continuity_gaps`, `freshness`, `daily_hourly_reconciliation` | Recorded; the load continues |

## Workflow

If the user asks you to refresh, reload or fix anything, open the answer by saying you can't: you are read-only and an operator must run it. Then investigate and report as below.

```
- [ ] 1. warehouse_reconciliation, warehouse_mart_parity and warehouse_quality together in one step.
- [ ] 2. For each asset with a problem: warehouse_lineage(symbol) to tie it to an archive and batch.
```

## Reading the result

| Observation | Reading |
|---|---|
| `accounting_delta` ≠ 0 | Rows lost or double-counted inside that batch. Point at that batch's load report. |
| `aggregates_match` false, mart lower, newest batch still running or failed | Mart not refreshed yet. Timing, not data loss. |
| `aggregates_match` false, newest batch succeeded | Mart is stale or its scope differs. Recommend a refresh check, not a reload. |
| `mart_candles` null or `fact_candles` null | Asset present on one side only |
| error check with `failed_rows` > 0 | Those rows were rejected; `rejected_rows` in the same batch should match |
| warning check failed | Data loaded but flagged; read `check_name` for what |
| Quality returned no rows | No checks in 7 days. That is "not checked", not "passed". |

## Report

One row per problem, every asset included, even ones the user didn't name:

```markdown
**<n problems> found: <one-line summary>.**

| Asset | What disagrees | Values | Batch | Likely reading |
|---|---|---|---|---|
| <symbol> | fact vs mart | <fact_candles> vs <mart_candles> candles (gap <candle_gap>), volume gap <volume_gap> USDT | <batch_id> | <reading from the table> |

Next step: <scoped operator investigation>.

[skill:warehouse-reconciliation]
```

If nothing disagrees, say so in one line and name the tools that showed it.

## Gotchas

- Quote only differences the tools returned. Don't compute percentages or "about N %" figures the tools didn't give.
- Accepted is not inserted: compare `changed_rows` only when the user asks what actually changed.
- Never refresh marts, re-run loads or modify warehouse data. Recommend; don't act.

Every figure in the answer comes from a tool result in this conversation. Placeholders in <angle brackets> show where a tool value goes; never fill them with example or estimated numbers, and say "not checked" instead.
