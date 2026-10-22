---
name: forecast-explainer
description: Explains the BTC next-hour forecast, how big the predicted move is, and how far to trust it given live accuracy. Use when the user asks what the forecast says, why it says up or down, whether to trust it, or how the model works.
---

# Forecast explainer

## What `predict_hourly` returns

| Field | Meaning |
|---|---|
| `model_id` | `btc_hourly_frozen_ensemble_v1`: a frozen CatBoost ensemble, not retrained online |
| `cutoff` | Last closed hour the model saw |
| `target_open`, `target_close` | The hour being predicted |
| `timing` | `target_hour_in_progress`, or `historical` if that hour already closed |
| `target_already_started` | True when the target hour has begun; the forecast is late for acting on |
| `predicted_log_return` | The model output |
| `reference_close_usdt`, `predicted_close_usdt` | Last close and `reference × exp(log return)` |
| `direction` | Sign of the log return: up, down or flat |
| `research_test` | Retrospective test: `relative_mae`, `directional_accuracy_pct`, `sample_hours`, `period` |

## How to explain the size

`predicted_log_return × 100` is approximately the percent move. Compare it with recent hourly moves only if a tool returned them; otherwise give the predicted close next to the reference close.

## How to explain trust

Trust comes from live accuracy, not from the direction.

| Evidence | Say |
|---|---|
| `model_health` live `relative_mae` below 1, `reliable` true | Beats predicting no change on live data, by that margin |
| Live `relative_mae` near 1 or above | About as good as, or worse than, predicting no change |
| `reliable` false | Live record is too short to judge; give `n` |
| Only `research_test` | Retrospective result for <period>, not current accuracy |

## Workflow

```
- [ ] 1. predict_hourly and model_health together in one step.
```

## Report

```markdown
**The model predicts <direction> for <target_open> to <target_close> UTC: <predicted_close_usdt> USDT from <reference_close_usdt> (about <log return × 100> %).**

- Trust: <live relative MAE and n, or "not yet reliable">.
- Timing: <"the target hour has started" if target_already_started>.
- This is a point estimate, not a probability or a trading signal.
```

## Gotchas

- Not a probability, not a confidence interval, not advice.
- `directional_accuracy_pct` near 50 means the direction is close to a coin flip. Say so if you quote it.
- Never present `research_test` as live performance.

Every figure in the answer comes from a tool result in this conversation. Placeholders in <angle brackets> show where a tool value goes; never fill them with example or estimated numbers, and say "not checked" instead.
