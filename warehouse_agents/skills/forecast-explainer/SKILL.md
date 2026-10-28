---
name: forecast-explainer
description: Explains the BTC/ETH next-UTC-daily-close support forecast, quantile uncertainty, recent causal performance and hourly context. Use when the user asks what the forecast says, whether to trust it, or how it works.
---

# Forecast explainer

The reader is usually not a data scientist. They want: up or down, by how much, to what price, and can I trust it.

## What `forecast_support` returns

| Field | Use it as |
|---|---|
| `forecast.target_open/target_close` | UTC day being predicted |
| `forecast.reference_close_usdt` | Last fully closed daily close |
| `forecast.predicted_close_q50_usdt` | Point estimate for target close |
| `forecast.predicted_close_q10/q90_usdt` | Empirical lower/upper estimates; not guaranteed 80% confidence |
| `forecast.interval_crosses_zero` | True means the interval includes both up and down outcomes |
| `recent_performance.directional_accuracy` | Return-sign accuracy on the causal recent window |
| `recent_performance.relative_mae` | Below 1 beats no-change MAE; above 1 does not |
| `hourly_trend.slope_per_hour` + `regression_r_squared` | Direction and strength of the closed-hour trend |

## How to say trust

| Evidence | Plain words |
|---|---|
| recent `relative_mae` below 1 | "Recent close error beat guessing no change" |
| recent `relative_mae` at/above 1 | "Recent close error did not beat guessing no change" |
| q10–q90 crosses zero | "The uncertainty range supports both up and down outcomes" |
| accuracy near 50% | "Recent direction accuracy is close to a coin flip" |

## Workflow

```
- [ ] Call forecast_support once with the requested BTC/ETH symbol and bounded windows.
```

## Answer

The app draws a "current vs predicted price" chart under the answer. Keep the text to this:

```markdown
**<asset>: expected to <rise/fall> to <q50 price> USDT at the next UTC daily close.**

| Last daily close | q50 estimate | Recent direction accuracy |
|---|---|---|
| <reference_close_usdt> USDT | <predicted_close_q50_usdt> USDT | <directional_accuracy>% of days |

Low confidence: <one plain trust sentence from the table above>.
```

Add q10–q90 in one short line. If it crosses zero, explicitly say uncertainty includes both directions.

## Gotchas

- Never call q10–q90 an 80% certainty. Its empirical coverage is reported separately.
- Not a probability, not advice. Don't list limitations one by one; the single "Low confidence" line covers it.
- Round the percent to two decimals and prices to whole USDT.
- Write everything in the user's language, table headers included.
- The recent window is retrospective and causal, but not necessarily unseen/prospective test data.

Every figure in the answer comes from a tool result in this conversation. Placeholders in <angle brackets> show where a tool value goes; never fill them with example or estimated numbers, and say "not checked" instead.
