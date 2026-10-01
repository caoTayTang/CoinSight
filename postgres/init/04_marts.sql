-- OLAP data marts.
--
-- Heavy aggregations are materialized views; batch_etl.py refreshes them after
-- every load, so readers always see the latest warehouse state. Each mart keeps
-- source_code as a fixed grouping key so figures from different sources never
-- mix. Rolled-up rows are marked by a level column (or 'ALL' labels) instead of
-- bare NULLs, so they can be filtered without GROUPING() in client code.


-- Roll-up / drill-down: asset performance at month, quarter, year and
-- all-time level, built with ROLLUP over the date hierarchy.
create materialized view if not exists mart.mv_asset_period_summary as
select
    r.source_code,
    r.symbol,
    r.category,
    case grouping(d.year, d.quarter, d.month)
        when 0 then 'month'
        when 1 then 'quarter'
        when 3 then 'year'
        else 'all'
    end as period_level,
    d.year,
    d.quarter,
    d.month,
    min(r.full_date) as period_start,
    max(r.full_date) as period_end,
    count(*) as trading_days,
    (array_agg(r.open_price order by r.date_key))[1] as open_price,
    (array_agg(r.close_price order by r.date_key desc))[1] as close_price,
    max(r.high_price) as high_price,
    min(r.low_price) as low_price,
    (array_agg(r.close_price order by r.date_key desc))[1]
        / (array_agg(r.open_price order by r.date_key))[1] - 1 as period_return,
    avg(r.daily_return) as avg_daily_return,
    stddev_samp(r.daily_return) as daily_volatility,
    sum(r.volume_quote) as volume_usd,
    sum(r.trade_count) as trade_count
from mart.v_daily_return r
join dw.dim_date d using (date_key)
group by r.source_code, r.symbol, r.category, rollup (d.year, d.quarter, d.month);

create index if not exists mv_asset_period_summary_idx
    on mart.mv_asset_period_summary (period_level, year, quarter, month, symbol);


-- Slice / dice: coin categories across years and quarters, built with CUBE so
-- every combination of category, year and quarter has a subtotal.
-- Stablecoins are excluded because their price does not move by design.
create materialized view if not exists mart.mv_category_performance as
select
    r.source_code,
    case when grouping(r.category) = 1 then 'ALL' else r.category end as category,
    d.year,
    d.quarter,
    grouping(r.category, d.year, d.quarter) as grouping_id,
    count(distinct r.asset_key) as assets,
    count(*) as asset_days,
    avg(r.daily_return) as avg_daily_return,
    stddev_samp(r.daily_return) as daily_volatility,
    avg(r.intraday_range) as avg_intraday_range,
    sum(r.volume_quote) as volume_usd
from mart.v_daily_return r
join dw.dim_date d using (date_key)
where not r.is_stablecoin
group by r.source_code, cube (r.category, d.year, d.quarter);


-- Intraday pattern: trading activity and price movement by UTC hour and
-- trading session, per asset and across all assets.
create materialized view if not exists mart.mv_hourly_activity as
with hourly as (
    select
        f.asset_key,
        f.source_key,
        f.time_key,
        f.volume_quote,
        f.close_price
            / lag(f.close_price) over (
                partition by f.asset_key, f.source_key order by f.open_time
            )
            - 1 as hourly_return,
        (f.high_price - f.low_price) / f.open_price as hourly_range
    from dw.fact_ohlcv_hourly f
)
select
    s.source_code,
    case when grouping(a.symbol) = 1 then 'ALL' else a.symbol end as symbol,
    case when grouping(t.trading_session) = 1 then 'ALL' else t.trading_session end
        as trading_session,
    t.time_key as hour_utc,
    count(*) as candles,
    avg(h.volume_quote) as avg_volume_usd,
    sum(h.volume_quote) as volume_usd,
    avg(abs(h.hourly_return)) as avg_abs_return,
    avg(h.hourly_range) as avg_range
from hourly h
join dw.dim_asset a using (asset_key)
join dw.dim_source s using (source_key)
join dw.dim_time t using (time_key)
group by s.source_code, grouping sets (
    (a.symbol, t.trading_session, t.time_key),
    (a.symbol, t.trading_session),
    (a.symbol),
    (t.trading_session, t.time_key),
    (t.trading_session),
    ()
);


-- Top 3 gainers and losers per quarter. trading_days shows partial quarters,
-- such as the current one or the quarter an asset was listed.
create or replace view mart.v_top_movers as
select *
from (
    select
        source_code,
        year,
        quarter,
        symbol,
        category,
        trading_days,
        period_return,
        rank() over (
            partition by source_code, year, quarter order by period_return desc
        ) as gain_rank,
        rank() over (
            partition by source_code, year, quarter order by period_return
        ) as loss_rank
    from mart.mv_asset_period_summary
    where period_level = 'quarter'
) ranked
where gain_rank <= 3 or loss_rank <= 3;
