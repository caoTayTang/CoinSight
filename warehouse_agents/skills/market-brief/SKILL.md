---
name: market-brief
description: Market questions about BTC, ETH or SOL: price now, recent move, freshness of the data, the daily model, "tóm tắt thị trường". Use for the answer's structure and what to check before stating a number.
---
# Market brief

## Steps
1. `market_data` with `live_summary` for the current price (last closed one-minute candles), `snapshot` for the
   latest closed daily candle. Call both when the user wants a brief.
2. Only if asked about the outlook: `market_data` `daily_direction`, and for BTC `predict_hourly`.
3. Only if something looks unusual: `detect_market_anomaly` (BTC).

## How to report
- First line: the price with its time and freshness, in the form "<asset> <price> USDT at <time> UTC (<age> old)".
- If data is stale (freshness warning or older than a few minutes for live data), say so before anything else.
- Then 2–4 bullets: recent move, volume or coverage, model outputs if requested.
- Prices are USDT on Binance Spot, not USD. Never give buy/sell advice; describe, don't recommend.

Every figure in the answer comes from a tool result in this conversation. Placeholders in <angle brackets> show
where a tool value goes; never fill them with example or estimated numbers, and say "not checked" instead.
