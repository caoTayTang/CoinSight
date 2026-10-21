-- Durable per-load evidence, retained even when staging is cleared.
create table if not exists meta.warehouse_load_report (
    batch_id bigint not null references meta.etl_batch,
    source_code text not null,
    symbol text not null,
    candle_interval text not null,
    staging_rows bigint not null,
    rejected_rows bigint not null,
    duplicate_rows bigint not null,
    accepted_rows bigint not null,
    changed_rows bigint not null default 0,
    primary key (batch_id, source_code, symbol, candle_interval)
);

alter table dw.fact_ohlcv_daily add column if not exists source_file text;
alter table dw.fact_ohlcv_daily add column if not exists extract_batch_id bigint;
alter table dw.fact_ohlcv_hourly add column if not exists source_file text;
alter table dw.fact_ohlcv_hourly add column if not exists extract_batch_id bigint;

-- No inferred lineage for old facts: missing source_file remains explicit.
create or replace view meta.v_fact_archive_lineage as
select a.symbol, '1d'::text as candle_interval,
       d.full_date::timestamp at time zone 'UTC' as open_time,
       f.close_price, f.batch_id, f.extract_batch_id, f.source_file,
       m.sha256, m.source_url
from dw.fact_ohlcv_daily f
join dw.dim_asset a using (asset_key)
join dw.dim_date d using (date_key)
left join meta.source_file_manifest m on m.extract_batch_id = f.extract_batch_id
    and m.source_file = f.source_file
union all
select a.symbol, '1h', f.open_time, f.close_price, f.batch_id,
       f.extract_batch_id, f.source_file, m.sha256, m.source_url
from dw.fact_ohlcv_hourly f
join dw.dim_asset a using (asset_key)
left join meta.source_file_manifest m on m.extract_batch_id = f.extract_batch_id
    and m.source_file = f.source_file;

-- Coverage is only between the first and last observed candle, per source.
-- It does not claim coverage before listing or after the latest observation.
create or replace view meta.v_warehouse_coverage as
with candles as (
    select a.symbol, s.source_code, '1d'::text as candle_interval,
           d.full_date::timestamp at time zone 'UTC' as open_time
    from dw.fact_ohlcv_daily f
    join dw.dim_asset a using (asset_key)
    join dw.dim_source s using (source_key)
    join dw.dim_date d using (date_key)
    union all
    select a.symbol, s.source_code, '1h', f.open_time
    from dw.fact_ohlcv_hourly f
    join dw.dim_asset a using (asset_key)
    join dw.dim_source s using (source_key)
), summary as (
    select symbol, source_code, candle_interval, min(open_time) as first_open,
           max(open_time) as last_open, count(*) as fact_rows,
           count(distinct open_time) as distinct_candles
    from candles group by 1, 2, 3
)
select *, fact_rows - distinct_candles as duplicate_rows,
       (extract(epoch from last_open - first_open) /
          case candle_interval when '1d' then 86400 else 3600 end)::bigint + 1
          as expected_candles,
       (extract(epoch from last_open - first_open) /
          case candle_interval when '1d' then 86400 else 3600 end)::bigint + 1
          - distinct_candles as missing_candles
from summary;
