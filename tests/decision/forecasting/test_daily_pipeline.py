from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pipeline.decision.config import ForecastDataConfig
from pipeline.decision.data.dataloader import ForecastDataModule
from pipeline.decision.data.feature_extractor import (
    DAILY_MAX_ROLLING_WINDOW,
    DAILY_SEQUENCE_FEATURES,
    DailyFeatureExtractor,
    MultiAssetFeatureFusion,
    fused_sequence_feature_names,
)
from pipeline.decision.data.scaler import SequenceScaler, TargetScaler
from pipeline.decision.data.sample_index import SampleIndexBuilder
from pipeline.decision.data.snapshot import SnapshotBuilder
from pipeline.decision.data.split import TimeSeriesSplitter
from pipeline.decision.inference.predictor import ForecastPredictor
from pipeline.decision.types import (
    DatasetSplit,
    ModelType,
    SplitBoundaries,
    utc_datetime,
)


def daily_candles(count: int = 1200) -> pd.DataFrame:
    times = pd.date_range("2022-01-01", periods=count, freq="D", tz="UTC")
    index = np.arange(count, dtype=float)
    close = 100.0 * np.exp(index * 0.0005 + np.sin(index / 17.0) * 0.02)
    open_price = close * (1.0 + np.sin(index / 9.0) * 0.002)
    return pd.DataFrame({
        "symbol": "BTC",
        "open_time": times,
        "open_price": open_price,
        "high_price": np.maximum(open_price, close) * 1.01,
        "low_price": np.minimum(open_price, close) * 0.99,
        "close_price": close,
        "volume_quote": 1_000_000.0 + index * 1000.0,
        "trade_count": 10_000 + index.astype(int),
        "batch_id": 1,
        "loaded_at": times + pd.Timedelta(days=1, minutes=5),
    })


def daily_frames():
    candles = daily_candles()
    features = DailyFeatureExtractor().transform(candles)
    samples = SampleIndexBuilder().build(
        candles,
        features,
        lookback=90,
        horizon=1,
        frequency="1d",
    )
    boundaries = SplitBoundaries(
        pd.Timestamp("2024-01-01", tz="UTC").to_pydatetime(),
        pd.Timestamp("2025-01-01", tz="UTC").to_pydatetime(),
        pd.Timestamp("2025-04-15", tz="UTC").to_pydatetime(),
    )
    return candles, features, TimeSeriesSplitter().assign(samples, boundaries)


def daily_context_candles(count: int = 1200) -> pd.DataFrame:
    frames = []
    for symbol, multiplier in (("ETH", 1.2), ("SOL", 0.8)):
        frame = daily_candles(count).copy()
        frame["symbol"] = symbol
        for column in ("open_price", "high_price", "low_price", "close_price"):
            frame[column] *= multiplier
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def test_daily_features_are_warmup_safe_and_aligned():
    candles = daily_candles(250)
    features = DailyFeatureExtractor().transform(candles)

    assert tuple(DailyFeatureExtractor().feature_names()) == DAILY_SEQUENCE_FEATURES
    assert not features.loc[:DAILY_MAX_ROLLING_WINDOW - 1, "feature_valid"].any()
    assert features.loc[DAILY_MAX_ROLLING_WINDOW:, "feature_valid"].all()
    expected = np.log(
        candles.loc[100, "close_price"] / candles.loc[99, "close_price"]
    )
    assert np.isclose(features.loc[100, "log_return_1d"], expected)


def test_daily_v2_fuses_context_features_without_future_leakage():
    target = daily_candles(300)
    context = daily_context_candles(300)
    extractor = DailyFeatureExtractor("daily-return-v2")
    before = MultiAssetFeatureFusion().attach(
        extractor.transform(target),
        context,
        "BTC",
        ("BTC", "ETH", "SOL"),
        "daily-return-v2",
    )
    names = fused_sequence_feature_names(
        "BTC", ("ETH", "SOL"), "daily-return-v2"
    )

    assert len(DAILY_SEQUENCE_FEATURES) == 25
    assert len(names) == 75
    assert set(names).issubset(before.columns)
    assert before.loc[90, "feature_valid"]

    changed = context.copy()
    future = changed["open_time"] > target.loc[180, "open_time"]
    changed.loc[
        future, ["open_price", "high_price", "low_price", "close_price"]
    ] *= 2
    after = MultiAssetFeatureFusion().attach(
        extractor.transform(target),
        changed,
        "BTC",
        ("BTC", "ETH", "SOL"),
        "daily-return-v2",
    )
    pd.testing.assert_frame_equal(
        before.loc[:180, list(names)], after.loc[:180, list(names)]
    )


def test_daily_sample_target_is_next_close_return():
    candles, features, samples = daily_frames()
    valid = samples[samples["is_valid"]].iloc[0]

    expected = np.log(
        valid["actual_close_usdt"] / valid["reference_close_usdt"]
    )
    assert np.isclose(valid["target_log_return"], expected)
    assert valid["target_time"] - valid["latest_input_open_time"] == pd.Timedelta(days=1)
    assert valid["cutoff_time"] == valid["target_time"]


def test_daily_data_loader_serves_xgboost_and_recurrent_shapes():
    _, features, samples = daily_frames()

    xgb = ForecastDataModule.from_frames(
        features,
        samples,
        ModelType.XGBOOST,
        feature_version="daily-return-v1",
    )
    xgb.setup()
    assert xgb.input_shape()[0] > len(DAILY_SEQUENCE_FEATURES)
    assert len(xgb.tabular(DatasetSplit.TRAIN).y) > 0

    gru = ForecastDataModule.from_frames(
        features,
        samples,
        ModelType.GRU,
        feature_version="daily-return-v1",
        sequence_features=DAILY_SEQUENCE_FEATURES,
    )
    gru.setup()
    assert gru.input_shape() == (90, len(DAILY_SEQUENCE_FEATURES))
    rolling = gru.rolling_mean_return(DatasetSplit.VALIDATION, 30)
    assert len(rolling) == len(gru.targets(DatasetSplit.VALIDATION))
    assert np.isfinite(rolling).all()


def test_daily_v2_loader_serves_fused_recurrent_shape_and_rejects_xgboost():
    target = daily_candles()
    extractor = DailyFeatureExtractor("daily-return-v2")
    features = MultiAssetFeatureFusion().attach(
        extractor.transform(target),
        daily_context_candles(),
        "BTC",
        ("BTC", "ETH", "SOL"),
        "daily-return-v2",
    )
    samples = SampleIndexBuilder().build(
        target, features, lookback=90, horizon=1, frequency="1d"
    )
    boundaries = SplitBoundaries(
        pd.Timestamp("2024-01-01", tz="UTC").to_pydatetime(),
        pd.Timestamp("2025-01-01", tz="UTC").to_pydatetime(),
        pd.Timestamp("2025-04-15", tz="UTC").to_pydatetime(),
    )
    samples = TimeSeriesSplitter().assign(samples, boundaries)
    names = fused_sequence_feature_names(
        "BTC", ("ETH", "SOL"), "daily-return-v2"
    )
    gru = ForecastDataModule.from_frames(
        features,
        samples,
        ModelType.GRU,
        feature_version="daily-return-v2",
        sequence_features=names,
    )
    gru.setup()

    assert gru.input_shape() == (90, 75)

    xgb = ForecastDataModule.from_frames(
        features,
        samples,
        ModelType.XGBOOST,
        feature_version="daily-return-v2",
    )
    with pytest.raises(ValueError, match="sequence models only"):
        xgb.setup()


def test_daily_inference_targets_the_next_daily_close():
    class ConstantModel:
        def predict(self, tabular):
            assert tabular.X.shape[0] == 1
            return np.asarray([0.01])

    frame = daily_candles(180)
    predictor = ForecastPredictor(
        ConstantModel(),
        ModelType.XGBOOST,
        "daily-run",
        lookback=90,
        feature_version="daily-return-v1",
        frequency="1d",
    )

    result, batch_ids = predictor.predict(frame)

    assert result.target_time == (
        frame.open_time.iloc[-1] + pd.Timedelta(days=1)
    ).to_pydatetime()
    assert np.isclose(
        result.predicted_close_usdt,
        frame.close_price.iloc[-1] * np.exp(0.01),
    )
    assert batch_ids == (1,)


def test_daily_v2_sequence_inference_requires_aligned_context():
    torch = pytest.importorskip("torch")

    class ShapeCheckingModel(torch.nn.Module):
        def forward(self, inputs):
            assert tuple(inputs.shape[1:]) == (90, 75)
            return torch.zeros((len(inputs), 1), device=inputs.device)

    names = fused_sequence_feature_names(
        "BTC", ("ETH", "SOL"), "daily-return-v2"
    )
    scaler = SequenceScaler(names)
    scaler.mean_ = np.zeros(len(names), dtype=np.float64)
    scaler.scale_ = np.ones(len(names), dtype=np.float64)
    target_scaler = TargetScaler().fit(np.asarray([-0.01, 0.01]))
    predictor = ForecastPredictor(
        ShapeCheckingModel(),
        ModelType.GRU,
        "daily-v2-run",
        scaler=scaler,
        target_scaler=target_scaler,
        lookback=90,
        context_symbols=("BTC", "ETH", "SOL"),
        feature_version="daily-return-v2",
        frequency="1d",
    )
    target = daily_candles(180)
    context = daily_context_candles(180)

    with pytest.raises(ValueError, match="requires context candles"):
        predictor.predict(target)
    result, _ = predictor.predict(target, context)

    assert result.symbol == "BTC"
    assert result.target_time == (
        target.open_time.iloc[-1] + pd.Timedelta(days=1)
    ).to_pydatetime()


def test_daily_snapshot_records_period_contract(tmp_path):
    frame = daily_candles()

    class Repository:
        def fetch_candles(self, symbol, start, end):
            return frame[
                (frame["open_time"] >= start) & (frame["open_time"] < end)
            ].copy()

        def fetch_source_batch_ids(self, symbol, start, end):
            return [1]

    start = utc_datetime("2022-01-01")
    cutoff = utc_datetime("2025-04-15")
    config = ForecastDataConfig(
        symbols=("BTC",),
        source_code="binance",
        feature_version="daily-return-v1",
        lookback_hours=90,
        horizon_hours=1,
        validation_start=utc_datetime("2024-01-01"),
        test_start=utc_datetime("2025-01-01"),
        history_start={"BTC": start},
        rolling_baseline_hours=30,
        frequency="1d",
        minimum_month_samples=20,
    )

    snapshot = SnapshotBuilder(Repository(), config, tmp_path).build(
        "BTC", start, cutoff
    )

    assert snapshot.manifest["frequency"] == "1d"
    assert snapshot.manifest["lookback_periods"] == 90
    assert snapshot.manifest["horizon_periods"] == 1
    assert snapshot.manifest["rolling_baseline_periods"] == 30
    assert snapshot.manifest["lookback_hours"] is None
    assert snapshot.manifest["row_counts"]["valid_samples"] > 0


def test_daily_v2_snapshot_records_fused_context_contract(tmp_path):
    target = daily_candles()
    context = daily_context_candles()
    warehouse = pd.concat([target, context], ignore_index=True)

    class Repository:
        def fetch_candles(self, symbol, start, end):
            return warehouse[
                warehouse["symbol"].eq(symbol)
                & (warehouse["open_time"] >= start)
                & (warehouse["open_time"] < end)
            ].copy()

        def fetch_candles_many(self, symbols, start, end):
            return warehouse[
                warehouse["symbol"].isin(symbols)
                & (warehouse["open_time"] >= start)
                & (warehouse["open_time"] < end)
            ].copy()

        def fetch_source_batch_ids(self, symbol, start, end):
            return [1]

    start = utc_datetime("2022-01-01")
    cutoff = utc_datetime("2025-04-15")
    config = ForecastDataConfig(
        symbols=("BTC",),
        source_code="binance",
        feature_version="daily-return-v2",
        lookback_hours=90,
        horizon_hours=1,
        validation_start=utc_datetime("2024-01-01"),
        test_start=utc_datetime("2025-01-01"),
        history_start={"BTC": start},
        context_symbols=("BTC", "ETH", "SOL"),
        rolling_baseline_hours=30,
        frequency="1d",
        minimum_month_samples=20,
    )

    snapshot = SnapshotBuilder(Repository(), config, tmp_path).build(
        "BTC", start, cutoff
    )
    features = snapshot.read_features()

    assert snapshot.manifest["feature_version"] == "daily-return-v2"
    assert snapshot.manifest["context_symbols"] == ["ETH", "SOL"]
    assert snapshot.manifest["asset_order"] == ["BTC", "ETH", "SOL"]
    assert len(snapshot.manifest["sequence_feature_names"]) == 75
    assert features.filter(regex="^(BTC|ETH|SOL)__").shape[1] == 75
    assert snapshot.manifest["row_counts"]["valid_samples"] > 0
