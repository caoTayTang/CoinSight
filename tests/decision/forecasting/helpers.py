from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.decision.data.feature_extractor import HourlyFeatureExtractor
from pipeline.decision.data.sample_index import SampleIndexBuilder


def candles(count: int = 400, start: str = "2024-01-01T00:00:00Z") -> pd.DataFrame:
    times = pd.date_range(start, periods=count, freq="h", tz="UTC")
    close = 100 * np.exp(np.arange(count) * 0.0002 + np.sin(np.arange(count) / 10) * 0.001)
    open_price = close * 0.999
    return pd.DataFrame({
        "symbol": "BTC",
        "open_time": times,
        "open_price": open_price,
        "high_price": np.maximum(open_price, close) * 1.002,
        "low_price": np.minimum(open_price, close) * 0.998,
        "close_price": close,
        "volume_quote": 1_000 + np.arange(count) * 2,
        "trade_count": 100 + np.arange(count),
        "batch_id": 1,
        "loaded_at": times + pd.Timedelta(minutes=5),
    })


def feature_samples(count: int = 400):
    raw = candles(count)
    features = HourlyFeatureExtractor().transform(raw)
    samples = SampleIndexBuilder().build(raw, features)
    return raw, features, samples
