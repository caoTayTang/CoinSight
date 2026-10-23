---
name: model-drift
description: Judges whether the BTC forecast and anomaly models still fit current data, separating input drift (PSI) from measured live accuracy (prediction ledger). Use for model health, drift, PSI, "is the model still good", or current MAE or accuracy questions.
---

# Model drift

## What `model_health` returns

| Field | Model | Meaning |
|---|---|---|
| `data_drift[]` | Isolation Forest anomaly model | PSI per feature over the last 336 hours vs its training profile |
| `forecast_drift.flagged[]` | Hourly forecast | Short-window features with PSI ≥ 0.25 over the last 30 days (`window_feature_rows`) |
| `forecast_drift.flagged_long_window[]` | Hourly forecast | `_72` / `_168` rolling features over the flag. They move slowly and reflect the current regime; report them separately, not as drift. |
| `forecast_drift.drift_watch` | Hourly forecast | True if any short-window feature is flagged |
| `live_performance.windows[]` | Hourly forecast | `n`, `mae`, `baseline_mae`, `relative_mae`, `directional_accuracy` per `window_label` |
| `live_performance.reliable` | Hourly forecast | False below 168 scored hours |
| `frozen_forecast_test`, `anomaly_test` | Both | Retrospective test results. History, not current performance. |

## How to read it

- PSI ≥ 0.25 is a watch flag. It is not a significance test, a probability, or proof the model is wrong. Hourly rows are correlated, so PSI is noisy.
- Live performance is the only measure of current accuracy. Each forecast was recorded before its target hour and scored after it closed.
- `relative_mae` = `mae / baseline_mae`, where the baseline predicts no change. Below 1 beats it; above 1 is worse.
- If `reliable` is false, say the live estimate is not yet reliable and give `n`.
- Drift with good live performance means "inputs changed, accuracy hasn't". Live performance worse than the baseline without drift points at the model, not the data.

## Workflow

```
- [ ] 1. model_health, warehouse_coverage(BTC) and warehouse_quality together in one step.
- [ ] 2. If coverage shows missing or duplicated hours, report that first: gaps produce false drift.
```

## Report

Write for someone who doesn't know PSI or MAE.

```markdown
**<Verdict in plain words: are recent inputs normal, and is the forecast still better than guessing no change?>**

| Model | Recent inputs | Recent accuracy |
|---|---|---|
| Hourly forecast | <"normal" or "different from training: <feature names>"> | <"better than / same as / worse than guessing no change" over <n> hours, or "too few hours to judge"> |
| Anomaly model | <"normal" or "different from training: <feature names>"> | not measured (no labels) |

[skill:model-drift]
```

The app draws the drift chart with the PSI values; don't list them. Give PSI, MAE or relative MAE numbers only
if the user asks for technical detail. Write "not available" for anything the tool marked unavailable.

## Gotchas

- Never present `frozen_forecast_test` or `anomaly_test` as current accuracy.
- Anomaly-feature PSI says nothing about forecast accuracy, and the reverse.
- Never recommend automatic retraining because of a flag. Recommend watching live performance.

Every figure in the answer comes from a tool result in this conversation. Placeholders in <angle brackets> show where a tool value goes; never fill them with example or estimated numbers, and say "not checked" instead.
