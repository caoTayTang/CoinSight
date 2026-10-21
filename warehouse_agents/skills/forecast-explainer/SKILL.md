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
- Give the size in plain terms: multiply the log return by 100 for an approximate percentage move, and compare it
  with the size of recent hourly moves if a tool returned them.
- Trust comes from live performance against the zero-return baseline, not from the sign. If relative MAE is near
  1.0, say the model is about as good as predicting no change.
- If the target hour already started (`target_already_started`), say the forecast is late for acting on.
- It is not a probability, a confidence interval or trading advice.

Every figure in the answer comes from a tool result in this conversation. Placeholders in <angle brackets> show
where a tool value goes; never fill them with example or estimated numbers, and say "not checked" instead.
