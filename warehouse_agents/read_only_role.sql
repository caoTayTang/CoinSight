-- Run manually as schema owner/admin on the intended warehouse.
-- Set authentication separately (e.g. psql \password coinsight_observer).
-- This script does not grant writes, ownership, CREATE or privileges on future tables.
do $$ begin
  if not exists (select 1 from pg_roles where rolname='coinsight_observer') then
    create role coinsight_observer login nosuperuser nocreatedb nocreaterole noinherit;
  end if;
end $$;
alter role coinsight_observer set default_transaction_read_only = on;
alter role coinsight_observer set statement_timeout = '4s';
grant usage on schema dw, meta, mart to coinsight_observer;
grant select on dw.fact_ohlcv_hourly, dw.dim_asset, dw.dim_source,
  meta.etl_batch, meta.warehouse_load_report, meta.dq_result,
  meta.v_fact_archive_lineage, mart.mv_hourly_activity to coinsight_observer;
