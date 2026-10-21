---
name: forecast-explainer
description: Questions about the BTC hourly forecast: what it predicts, how much to trust it, why it says up or down. Use to explain the output without overstating it.
---
# Explaining the hourly forecast

## Steps
1. `predict_hourly` for the current forecast (cutoff, target hour, predicted log return, predicted close).
2. `model_health` for live performance from the prediction ledger and feature drift.

## How to explain
- Say exactly what it is: a predicted log return for the next 1h candle, from a frozen model, made at the cutoff.
- Give the size in plain terms: a log return of 0.0004 is about +0.04%, which is tiny next to typical hourly moves.
- Trust comes from live performance against the zero-return baseline, not from the sign. If relative MAE is near
  1.0, say the model is about as good as predicting no change.
- If the target hour already started (`target_already_started`), say the forecast is late for acting on.
- It is not a probability, a confidence interval or trading advice.
