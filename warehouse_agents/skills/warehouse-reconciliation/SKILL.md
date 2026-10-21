---
name: warehouse-reconciliation
description: Batch accounting, mart parity or failed data quality checks ("đối soát", rows don't add up, mart differs from fact, a check failed). Use to localise the defect to a batch, a check or a stale mart.
---
# Reconciliation, mart parity and quality checks

## Steps
1. `warehouse_reconciliation`: staging rows must equal rejected + duplicate + accepted. A nonzero
   `accounting_delta` points at that batch and its load report. Accepted rows are not the same as newly inserted rows.
2. `warehouse_mart_parity`: compare fact candle counts and quote volume with the hourly mart, per asset.
   A difference can be refresh timing, scope or a load defect. Check the observed time and batch status first.
3. `warehouse_quality`: `check_name`, `failed_rows`, `passed` per batch.
4. `warehouse_lineage` to tie the affected facts to archive hashes and source files.
Call the independent tools in the same step.

## How to report
- One line per problem found: asset, what disagrees, by how much, which batch.
- Report every asset with a problem, including assets the user didn't name.
- "No checks returned" is not "all checks passed": say which it is.

## Boundaries
Recommend a scoped operator investigation. Never refresh marts or modify warehouse data.

Every figure in the answer comes from a tool result in this conversation. Placeholders in <angle brackets> show
where a tool value goes; never fill them with example or estimated numbers, and say "not checked" instead.
