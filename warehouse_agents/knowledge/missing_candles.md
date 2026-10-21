# Missing candles / stale data / thiếu giờ dữ liệu

Use warehouse_coverage with symbol and hours to compare expected closed UTC hours to observed fact rows. The current open hour is excluded. Check missing_hours, last_observed_open and duplicated_grain_hours. Missing hours are data availability evidence, not a market anomaly.

Use warehouse_status to inspect recent ETL states, warehouse_lineage to locate source archives and load batches, and airflow_status to inspect DAG runs when configured. A running container does not prove data is fresh. An unavailable Airflow connection does not prove the scheduler is stopped.

Recovery must preserve the asset/source/interval/open_time grain. An operator should identify the affected archive and failed batch, inspect rejected rows, and follow the existing idempotent loader procedure. SRE only recommends checks and does not run backfills or SQL writes.
