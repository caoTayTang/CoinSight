-- Demo 2 (Đại). Same DataGrip connection as Demo 1.

-- 0. Before and after clearing the Airflow run: the count must not change
select count(*) from dw.fact_ohlcv_daily;

-- 1. Q3/2026 by category (CUBE; the 'ALL' row is the total)
select category, year, quarter, assets,
       round(avg_daily_return * 100, 2) as avg_daily_return_pct,
       round(daily_volatility * 100, 2) as daily_volatility_pct
from mart.mv_category_performance
where year = 2026 and quarter = 3;

-- 2. Q3/2026 top movers (rank())
select symbol, category, round(period_return * 100, 1) as return_pct, gain_rank
from mart.v_top_movers
where year = 2026 and quarter = 3
order by gain_rank;
