# Hourly BTC forecasting: an honest result

**Conclusion: next-hour BTC returns are close to unpredictable from public market data. The best
model beats a predict-zero-return baseline by under 1% MAE, so it is used as an agent tool with that
caveat attached, not as a trading signal.**

## Question

Predict the next closed hour's BTC/USDT log return from information available at the cutoff.
The metric is **Relative MAE** = model MAE / MAE of always predicting a 0 return. Below 1.0 beats the baseline.

## Protocol (what makes the number trustworthy)

- **Causal features only.** Features at hour *t* use candles that closed at or before *t*. Changing future rows
  does not change earlier features, and a test checks this (`tests/decision/test_hourly_features.py`).
- **Purged time splits.** Train, validation and test periods never overlap, including the target's horizon.
- **Plans locked before fitting.** Each experiment's split, metric and candidate list was written down before
  training, so the model wasn't chosen by trying things on the test data.
- **Uncertainty reported.** Circular block bootstrap (168-hour blocks, 2,000 draws).

## Results

| Model | Period | Hours | Relative MAE |
|---|---|---:|---:|
| Best ensemble (2× CatBoost, fixed weights) | Jul–Dec 2025 (selection, seen several times) | 4,416 | **0.9929** (95% bootstrap 0.9900–0.9961) |
| CatBoost candidate | same | 4,416 | 0.9940 |
| XGBoost winner | same | 4,416 | 0.9957 |
| TCN / LSTM, BTC only or pooled over 8 assets | same | 4,416 | 0.9974–0.9987 |
| Frozen bundle served by the agent | Jan–Oct 2026, retrospective | 6,984 | **0.9970** |

A 0.97 target was set and kept fixed. It was **not reached**. The research tried other model families,
intrahour, derivatives, order-book and cross-asset features, and ensembles; the scripts are archived under
`research/hourly/` and the full log is in [hourly_mae_097_research.md](hourly_mae_097_research.md).

## What this means for the product

- The forecast is exposed to the agent as a tool, and its description says it is a 0.997-relative-MAE
  forecast. The agent must not present it as a trading signal (see the `trading_advice` eval cases).
- The interesting engineering is the protocol: leakage-safe features, locked plans and reported uncertainty.
  Here it produced a defensible negative result, not an overfit "95% accuracy" claim.

## Anomaly detection (companion model)

An Isolation Forest trained on 2023–2024 and calibrated on 2025 flags 78 of 6,984 hours in 2026 (1.12%),
against 101 (1.45%) for a fixed median/MAD rule. There are no labeled anomalies, so these are alert
rates, not precision or recall.
