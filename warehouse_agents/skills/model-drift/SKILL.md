---
name: model-drift
description: Model health, feature drift, PSI, "is the model still good", current accuracy or MAE of the forecast or anomaly models. Use to separate input drift from measured live performance.
---
# Model drift and live performance

## Steps
1. `model_health`: for each model it returns feature drift (PSI against that model's training reference) and,
   for forecasting models, live performance from the prediction ledger.
2. Rule out data problems first: `warehouse_coverage` and `warehouse_quality`. Missing or duplicated candles
   produce false drift.

## How to read it
- PSI ≥ 0.25 is a heuristic watch flag. It isn't a significance test, a probability, or proof the model is broken.
  Hourly rows are correlated and the window is small, so PSI is noisy.
- Live performance comes from forecasts recorded before each target hour and scored after it closed
  (`ml.model_performance`). Report n, MAE, the zero-return baseline MAE and relative MAE. With fewer than
  ~168 scored hours, say the estimate is still unreliable.
- Relative MAE below 1.0 means better than predicting "no change"; above 1.0 means worse.
- Retrospective test metrics are history, not current performance. Never present them as current.

## How to report
A small table per model: drift flags (feature, PSI), live n / MAE / relative MAE per window. Then one sentence
on what it means and what to watch. Never recommend automatic retraining because of a flag.

Every figure in the answer comes from a tool result in this conversation. Placeholders in <angle brackets> show
where a tool value goes; never fill them with example or estimated numbers, and say "not checked" instead.
