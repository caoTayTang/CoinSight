-- OLAP query examples for the CoinSight warehouse.
--
-- Each section answers one business question and demonstrates one OLAP
-- operation. Run all of them with `make olap`, or copy a single query into
-- psql. Queries read the mart materialized views where one fits, and the star
-- schema (dw facts joined to dimensions) otherwise.

\pset null '-'


\echo '== 1. ROLL-UP: how did BTC perform in 2025, from months up to the whole year? =='
-- The mart is built with ROLLUP(year, quarter, month); period_level tells which
-- level each row belongs to.
select
    period_level,
    year,
    quarter,
    month,
    trading_days,
    round(period_return * 100, 2) as return_pct,
    round(daily_volatility * 100, 2) as daily_volatility_pct,
    round(volume_usd / 1e9, 2) as volume_busd
from mart.mv_asset_period_summary
where symbol = 'BTC'
  and (year = 2025 or period_level = 'all')
order by year nulls last, quarter nulls last, month nulls last;


\echo '== 2a. DRILL-DOWN (year -> month): which month of 2025 was worst for BTC? =='
select month, round(period_return * 100, 2) as return_pct
from mart.mv_asset_period_summary
where symbol = 'BTC' and year = 2025 and period_level = 'month'
order by period_return
limit 3;

\echo '== 2b. DRILL-DOWN (month -> day): the five worst days inside that month =='
with worst_month as (
    select year, month
    from mart.mv_asset_period_summary
    where symbol = 'BTC' and year = 2025 and period_level = 'month'
    order by period_return
    limit 1
)
select r.full_date, round(r.daily_return * 100, 2) as return_pct,
       round(r.volume_quote / 1e9, 2) as volume_busd
from mart.v_daily_return r
join dw.dim_date d using (date_key)
join worst_month w on w.year = d.year and w.month = d.month
where r.symbol = 'BTC'
order by r.daily_return
limit 5;

\echo '== 2c. DRILL-DOWN (day -> hour): hourly candles of the worst day in that month =='
with worst_month as (
    select year, month
    from mart.mv_asset_period_summary
    where symbol = 'BTC' and year = 2025 and period_level = 'month'
    order by period_return
    limit 1
),
worst_day as (
    select r.date_key
    from mart.v_daily_return r
    join dw.dim_date d using (date_key)
    join worst_month w on w.year = d.year and w.month = d.month
    where r.symbol = 'BTC'
    order by r.daily_return
    limit 1
)
select d.full_date, t.hour_label, t.trading_session,
       round(f.open_price, 2) as open_price, round(f.close_price, 2) as close_price,
       round((f.close_price / f.open_price - 1) * 100, 2) as hour_return_pct,
       round(f.volume_quote / 1e6, 1) as volume_musd
from dw.fact_ohlcv_hourly f
join worst_day w using (date_key)
join dw.dim_asset a using (asset_key)
join dw.dim_date d using (date_key)
join dw.dim_time t using (time_key)
where a.symbol = 'BTC'
order by t.time_key;


\echo '== 3. SLICE (category = layer-1): yearly return of each Layer-1 coin =='
select symbol, year, round(period_return * 100, 1) as return_pct
from mart.mv_asset_period_summary
where category = 'layer-1' and period_level = 'year' and year between 2023 and 2025
order by year, period_return desc;


\echo '== 4. DICE (meme + payments, 2024-2025, weekend vs weekday): does trading slow down at weekends? =='
-- Queries the star schema directly: fact + asset + date dimensions.
select
    a.category,
    d.year,
    case when d.is_weekend then 'weekend' else 'weekday' end as day_type,
    count(*) as asset_days,
    round(avg(f.volume_quote) / 1e6, 1) as avg_daily_volume_musd,
    round(avg((f.high_price - f.low_price) / f.open_price) * 100, 2) as avg_range_pct
from dw.fact_ohlcv_daily f
join dw.dim_asset a using (asset_key)
join dw.dim_date d using (date_key)
where a.category in ('meme', 'payments')
  and d.year between 2024 and 2025
group by a.category, d.year, d.is_weekend
order by a.category, d.year, day_type;


\echo '== 5. PIVOT: monthly return (%) of BTC, ETH and SOL in 2025, one column per coin =='
select
    month,
    round(max(period_return) filter (where symbol = 'BTC') * 100, 1) as btc,
    round(max(period_return) filter (where symbol = 'ETH') * 100, 1) as eth,
    round(max(period_return) filter (where symbol = 'SOL') * 100, 1) as sol
from mart.mv_asset_period_summary
where year = 2025 and period_level = 'month'
group by month
order by month;


\echo '== 6. ROLLUP on the star schema: trading volume by category and year with subtotals =='
select
    case when grouping(a.category) = 1 then 'ALL' else a.category end as category,
    case when grouping(d.year) = 1 then 'ALL' else d.year::text end as year,
    round(sum(f.volume_quote) / 1e9, 1) as volume_busd
from dw.fact_ohlcv_daily f
join dw.dim_asset a using (asset_key)
join dw.dim_date d using (date_key)
where d.year >= 2024
group by rollup (a.category, d.year)
order by a.category nulls last, d.year nulls last;


\echo '== 7. CUBE: which category is riskiest, per year and overall? =='
-- mv_category_performance is built with CUBE(category, year, quarter);
-- grouping_id = 1 keeps the (category, year) rows, 3 the per-category totals
-- over every year since 2020.
select
    category,
    coalesce(year::text, 'ALL') as year,
    assets,
    round(avg_daily_return * 100, 3) as avg_daily_return_pct,
    round(daily_volatility * 100, 2) as daily_volatility_pct
from mart.mv_category_performance
where grouping_id in (1, 3) and category <> 'ALL' and (year is null or year >= 2024)
order by category, year nulls last;


\echo '== 8. Intraday pattern: which trading session is most active? =='
select
    trading_session,
    candles,
    round(avg_volume_usd / 1e6, 1) as avg_hourly_volume_musd,
    round(avg_abs_return * 100, 3) as avg_abs_hourly_return_pct,
    round(volume_usd / sum(volume_usd) filter (where trading_session <> 'ALL') over () * 100, 1)
        as share_of_volume_pct
from mart.mv_hourly_activity
where symbol = 'ALL' and hour_utc is null
order by trading_session;


\echo '== 9. Top movers: best and worst coins of each quarter in 2025 =='
select year, quarter, symbol, category,
       round(period_return * 100, 1) as return_pct, gain_rank, loss_rank
from mart.v_top_movers
where year = 2025 and (gain_rank = 1 or loss_rank = 1)
order by quarter, gain_rank;
