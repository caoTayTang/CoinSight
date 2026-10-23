---
name: market-brief
description: Writes a short, timestamped market brief for BTC, ETH or SOL from warehouse data: current price, recent range, latest daily candle and, when asked, model outputs. Use for price, "how is the market", recent moves, data freshness, or "tóm tắt thị trường".
---

# Market brief

## What the tools return

`market_data(view, symbol)`:

| View | Gives | Use for |
|---|---|---|
| `live_summary` | Last closed one-minute candles: `window_high_usdt`, `window_low_usdt`, `candles_in_window`, `recent_closes[]` (last 15, with `open_time`) | Price now and the recent range |
| `snapshot` | Latest closed daily candle | Today's or yesterday's open, high, low, close, volume |
| `daily_direction` | The daily direction model's output | Only when asked about the outlook |

The price now is the last entry of `recent_closes`, at its `open_time`. Every response is stamped with `observed_at`; age = `observed_at` minus that candle time.

`predict_hourly` (BTC only) and `detect_market_anomaly` (BTC only) are model outputs, not market data.

## Workflow

```
- [ ] 1. market_data live_summary and snapshot together, for each asset asked about.
- [ ] 2. Only if asked about the outlook: daily_direction; for BTC also predict_hourly.
- [ ] 3. Only if the user asks whether something is unusual: detect_market_anomaly (BTC).
```

## Freshness

| Age of the last one-minute close | Say |
|---|---|
| A few minutes or less | Nothing extra |
| Older | Lead with "Live data is <age> old" before any price |
| `status` unavailable | "Live price not available", then the daily snapshot with its date |

## Report

```markdown
**<asset> is <last close> USDT** (at <open_time> UTC).

| Last hour low | Last hour high | Latest daily close (<date>) |
|---|---|---|
| <window_low_usdt> | <window_high_usdt> | <close> |
```

One table, no bullets restating it. For several assets, one row per asset in the same table. Add a model output
line only if the user asked for the outlook. The app already shows the price chart, so don't describe its shape.

## Gotchas

- Prices are USDT on Binance Spot. Write USDT, not USD or $.
- Only compute a percentage change if both prices come from the tools, and show both.
- Describe, never recommend. No buy, sell, entry or target levels.

Every figure in the answer comes from a tool result in this conversation. Placeholders in <angle brackets> show where a tool value goes; never fill them with example or estimated numbers, and say "not checked" instead.
