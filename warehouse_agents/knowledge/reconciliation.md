# Warehouse reconciliation / mart mismatch / đối soát

Use warehouse_reconciliation to verify staging_rows equals rejected_rows plus duplicate_rows plus accepted_rows. Nonzero accounting_delta needs investigation of the batch and its load report; do not equate accepted_rows with newly inserted rows.

Use warehouse_mart_parity to compare fact candle totals and quote volume to the materialized hourly activity mart. A mismatch may reflect refresh timing, scope differences or a load defect. Read the observed time and batch status before asserting corruption.

Use warehouse_quality for check_name, failed_rows and passed, then warehouse_lineage to connect facts to archive hashes and source files. No returned quality checks is not proof of perfect data. Recommend a scoped operator investigation; do not refresh marts or modify warehouse data automatically.
