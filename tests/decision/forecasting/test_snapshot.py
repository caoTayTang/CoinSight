import pytest
import pandas as pd

pytest.importorskip("pyarrow")

from pipeline.decision.config import ForecastDataConfig
from pipeline.decision.data.snapshot import SnapshotBuilder
from pipeline.decision.types import utc_datetime
from tests.decision.forecasting.helpers import candles


class FakeRepository:
    def __init__(self, frame):
        self.frame = frame

    def fetch_candles(self, symbol, start, end):
        return self.frame[
            (self.frame.open_time >= start) & (self.frame.open_time < end)
        ].copy()

    def fetch_source_batch_ids(self, symbol, start, end):
        return [1]


def test_snapshot_is_immutable_checksummed_and_reusable(tmp_path):
    frame = candles(300, "2024-01-01T00:00:00Z")
    start = utc_datetime("2024-01-01T00:00:00Z")
    cutoff = utc_datetime("2024-01-13T00:00:00Z")
    config = ForecastDataConfig(
        symbols=("BTC",), source_code="binance", feature_version="hourly-return-v1",
        lookback_hours=168, horizon_hours=1,
        validation_start=utc_datetime("2024-01-08T12:00:00Z"),
        test_start=utc_datetime("2024-01-10T12:00:00Z"),
        history_start={"BTC": start},
    )
    builder = SnapshotBuilder(FakeRepository(frame), config, tmp_path)

    first = builder.build("BTC", start, cutoff)
    second = builder.build("BTC", start, cutoff)

    assert first.snapshot_id == second.snapshot_id
    assert first.manifest["row_counts"]["candles"] == 288
    assert set(first.manifest["files"]) == {
        "candles.parquet", "features.parquet", "samples.parquet"
    }
    builder.verify_hashes(first)


class MultiSymbolFakeRepository:
    def __init__(self, frame):
        self.frame = frame

    def fetch_candles(self, symbol, start, end):
        return self.frame[
            (self.frame.symbol == symbol)
            & (self.frame.open_time >= start)
            & (self.frame.open_time < end)
        ].copy()

    def fetch_candles_many(self, symbols, start, end):
        return self.frame[
            self.frame.symbol.isin(symbols)
            & (self.frame.open_time >= start)
            & (self.frame.open_time < end)
        ].copy()

    def fetch_source_batch_ids(self, symbol, start, end):
        return [1]


def test_v2_snapshot_records_fused_cross_asset_features(tmp_path):
    frames = []
    for symbol, multiplier in (("BTC", 1.0), ("ETH", 1.1), ("SOL", 0.9)):
        frame = candles(900, "2024-01-01T00:00:00Z").copy()
        frame["symbol"] = symbol
        for column in ("open_price", "high_price", "low_price", "close_price"):
            frame[column] *= multiplier
        frames.append(frame)
    warehouse = pd.concat(frames, ignore_index=True)
    start = utc_datetime("2024-01-01T00:00:00Z")
    cutoff = utc_datetime("2024-02-07T12:00:00Z")
    config = ForecastDataConfig(
        symbols=("BTC",), source_code="binance", feature_version="hourly-return-v2",
        lookback_hours=336, horizon_hours=1,
        validation_start=utc_datetime("2024-01-30T00:00:00Z"),
        test_start=utc_datetime("2024-02-03T00:00:00Z"),
        history_start={"BTC": start},
        context_symbols=("BTC", "ETH", "SOL"),
    )

    snapshot = SnapshotBuilder(
        MultiSymbolFakeRepository(warehouse), config, tmp_path
    ).build("BTC", start, cutoff)
    features = snapshot.read_features()

    assert snapshot.manifest["context_symbols"] == ["ETH", "SOL"]
    assert snapshot.manifest["row_counts"]["context_candles"] == 1800
    assert len(snapshot.manifest["context_coverage"]) == 2
    assert snapshot.manifest["asset_order"] == ["BTC", "ETH", "SOL"]
    assert len(snapshot.manifest["sequence_feature_names"]) == 81
    assert features.loc[features["feature_valid"]].shape[0] > 0
    assert features.filter(regex="^(BTC|ETH|SOL)__").shape[1] == 81
    assert features.filter(regex="^(market_|relative_return)").shape[1] == 0


def test_v2_snapshot_supports_target_only_context_universe(tmp_path):
    frame = candles(900, "2024-01-01T00:00:00Z")
    start = utc_datetime("2024-01-01T00:00:00Z")
    cutoff = utc_datetime("2024-02-07T12:00:00Z")
    config = ForecastDataConfig(
        symbols=("BTC",), source_code="binance", feature_version="hourly-return-v2",
        lookback_hours=336, horizon_hours=1,
        validation_start=utc_datetime("2024-01-30T00:00:00Z"),
        test_start=utc_datetime("2024-02-03T00:00:00Z"),
        history_start={"BTC": start}, context_symbols=("BTC",),
    )

    snapshot = SnapshotBuilder(FakeRepository(frame), config, tmp_path).build(
        "BTC", start, cutoff
    )
    features = snapshot.read_features()

    assert snapshot.manifest["context_symbols"] == []
    assert snapshot.manifest["asset_order"] == ["BTC"]
    assert snapshot.manifest["row_counts"]["context_candles"] == 0
    assert len(snapshot.manifest["sequence_feature_names"]) == 27
    assert features.filter(regex="^BTC__").shape[1] == 27
