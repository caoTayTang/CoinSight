-- Demo 1 (Nhi). DataGrip: connect to localhost:5432, db crypto_dw, user crypto (through the SSH tunnel).
-- Run each statement with Ctrl+Enter (Cmd+Enter on Mac).

-- 1. Load report: staging_rows = rejected_rows + duplicate_rows + accepted_rows
select batch_id, symbol, candle_interval, staging_rows, rejected_rows,
       duplicate_rows, accepted_rows, changed_rows
from meta.warehouse_load_report
where symbol = 'BTC'
order by batch_id desc
limit 4;

-- 2. The BTC candle of 2026-10-24 in the fact table, joined to its dimensions
select d.full_date, a.symbol, a.category, s.source_code,
       f.open_price, f.high_price, f.low_price, f.close_price, f.batch_id
from dw.fact_ohlcv_daily f
join dw.dim_asset a using (asset_key)
join dw.dim_date d on d.date_key = f.date_key
join dw.dim_source s using (source_key)
where a.symbol = 'BTC' and d.full_date = date '2026-10-24';
