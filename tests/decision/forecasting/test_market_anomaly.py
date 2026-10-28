import json

import numpy as np
import pandas as pd
import pytest

from pipeline.decision.anomaly.bundle import MarketAnomalyBundle
from pipeline.decision.anomaly.features import (
    DAILY_FEATURES,
    HOURLY_FEATURES,
    extract_anomaly_features,
    required_candles,
)
from pipeline.decision.anomaly.training import AnomalyTrainingConfig, train_bundle


def candles(periods=900, frequency="1h", seed=42):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, periods)))
    opened = close * np.exp(rng.normal(0, 0.002, periods))
    high = np.maximum(opened, close) * (1 + rng.uniform(0.001, 0.02, periods))
    low = np.minimum(opened, close) * (1 - rng.uniform(0.001, 0.02, periods))
    return pd.DataFrame({
        "open_time": pd.date_range("2024-01-01", periods=periods, freq=frequency, tz="UTC"),
        "open_price": opened,
        "high_price": high,
        "low_price": low,
        "close_price": close,
        "volume_quote": rng.lognormal(10, 0.5, periods),
        "trade_count": rng.integers(100, 5000, periods),
    })


@pytest.mark.parametrize(
    "frequency,names", [("1h", HOURLY_FEATURES), ("1d", DAILY_FEATURES)]
)
def test_anomaly_features_are_causal_and_have_one_contract(frequency, names):
    raw = candles(250, frequency)
    full = extract_anomaly_features(raw, frequency)
    assert tuple(full.columns) == names
    assert full.iloc[: required_candles(frequency) - 1].isna().all().all()
    assert full.iloc[required_candles(frequency) - 1 :].notna().all().all()
    changed = raw.copy()
    changed.loc[200:, "close_price"] *= 2
    pd.testing.assert_frame_equal(
        full.iloc[:200], extract_anomaly_features(changed, frequency).iloc[:200]
    )


def test_gap_invalidates_every_window_that_contains_it():
    raw = candles(260, "1h").drop(index=180).reset_index(drop=True)
    result = extract_anomaly_features(raw, "1h")
    after_gap = result.index.get_loc(pd.Timestamp("2024-01-08 13:00:00+00:00"))
    assert result.iloc[after_gap : after_gap + 169].isna().all().all()


def test_invalid_ohlc_is_not_silently_used():
    raw = candles(250, "1d")
    raw.loc[200, "high_price"] = raw.loc[200, "low_price"]
    result = extract_anomaly_features(raw, "1d")
    assert result.iloc[200 : 200 + 50].isna().all().all()


def test_temporal_training_bundle_round_trip_and_checksum(tmp_path):
    raw = candles(1100, "1h")
    directory = train_bundle(
        raw,
        symbol="BTC",
        frequency="1h",
        train_start="2024-01-08T02:00:00Z",
        calibration_start="2024-01-25T00:00:00Z",
        test_start="2024-02-05T00:00:00Z",
        end="2024-02-15T00:00:00Z",
        version="test-v1",
        root=tmp_path,
        config=AnomalyTrainingConfig(n_estimators=32, max_samples=64, n_jobs=1),
        activate=True,
    )
    bundle = MarketAnomalyBundle.load("BTC", "1h", root=tmp_path)
    result = bundle.score(raw.iloc[-bundle.required_candles :])
    assert result["is_anomaly"] == (result["score"] >= result["threshold"])
    report = json.loads((directory / "evaluation.json").read_text())
    assert "accuracy" not in report
    assert report["splits"]["test"]["sample_count"] >= 20
    with (directory / "feature_config.json").open("a") as target:
        target.write("\n")
    with pytest.raises(ValueError, match="checksum"):
        MarketAnomalyBundle.load("BTC", "1h", root=tmp_path)
