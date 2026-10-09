"""Exercise the real DSS classifier on deterministic toy data, without Docker.

This is a software smoke test, not evidence of predictive value on crypto data.
Nothing is written to the warehouse, model artifact, or public API.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss

from pipeline.decision.direction_model import make_pipeline
from pipeline.decision.feature_builder import NUMERIC, SYMBOLS


def main() -> None:
    rng = np.random.default_rng(42)
    days = pd.date_range("2025-01-01", periods=240, freq="D", tz="UTC")
    rows = []
    for day in days:
        for symbol in SYMBOLS:
            return_1d = rng.normal(0, 0.03)
            return_7d = rng.normal(0, 0.07)
            range_pct = rng.uniform(0.005, 0.05)
            volume_change = rng.normal(0, 0.2)
            hourly_range = rng.uniform(0.005, 0.05)
            # A known toy pattern lets us check that fitting and scoring work.
            signal = return_1d / 0.03 + 0.5 * return_7d / 0.07
            target = int(signal + rng.normal(0, 0.5) > 0)
            rows.append((day, symbol, return_1d, return_7d, range_pct,
                         volume_change, hourly_range, target))
    frame = pd.DataFrame(rows, columns=["day", "symbol", *NUMERIC, "target"])
    validation_start, test_start = days[-60], days[-30]
    fit = frame[frame.day < validation_start - pd.Timedelta(days=1)]
    validation = frame[(frame.day >= validation_start) & (frame.day < test_start)]
    test = frame[frame.day >= test_start]
    model = make_pipeline().fit(fit, fit.target)
    prevalence = float(fit.target.mean())

    def score(holdout: pd.DataFrame) -> dict[str, float]:
        probability = model.predict_proba(holdout)[:, 1]
        return {
            "model_brier": float(brier_score_loss(holdout.target, probability)),
            "baseline_brier": float(brier_score_loss(
                holdout.target, np.full(len(holdout), prevalence))),
        }

    validation_score, test_score = score(validation), score(test)
    example = test[test.symbol == SYMBOLS[0]].iloc[-1:]
    print(json.dumps({
        "data": "synthetic_only",
        "model": "pooled_logistic_regression",
        "train_rows": len(fit),
        "validation_rows": len(validation),
        "test_rows": len(test),
        "validation": validation_score,
        "test": test_score,
        "example": {"symbol": SYMBOLS[0], "probability_up":
                    float(model.predict_proba(example)[0, 1])},
        "writes_to_warehouse": False,
    }, indent=2))


if __name__ == "__main__":
    main()
