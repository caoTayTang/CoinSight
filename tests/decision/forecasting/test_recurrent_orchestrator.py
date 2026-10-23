import json

import pandas as pd
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("pyarrow")

from pipeline.decision.artifacts.store import ArtifactStore
from pipeline.decision.config import ForecastDataConfig, RecurrentConfig, TrainingConfig
from pipeline.decision.data.snapshot import SnapshotBuilder
from pipeline.decision.training.run_training import TrainingOrchestrator
from pipeline.decision.types import ModelType, utc_datetime
from tests.decision.forecasting.helpers import candles


class FakeRepository:
    def __init__(self, frame):
        self.frame = frame

    def fetch_candles(self, symbol, start, end):
        return self.frame[
            (self.frame.symbol == symbol)
            & (self.frame.open_time >= start)
            & (self.frame.open_time < end)
        ].copy()

    def fetch_source_batch_ids(self, symbol, start, end):
        return [1]

    def fetch_candles_many(self, symbols, start, end):
        return self.frame[
            self.frame.symbol.isin(symbols)
            & (self.frame.open_time >= start)
            & (self.frame.open_time < end)
        ].copy()


def test_gru_training_orchestrator_saves_state_dict_and_scaler(tmp_path):
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
    snapshot = SnapshotBuilder(
        FakeRepository(frame), config, tmp_path / "snapshots"
    ).build("BTC", start, cutoff)
    store = ArtifactStore(tmp_path / "runs")
    orchestrator = TrainingOrchestrator(
        store,
        recurrent_config=RecurrentConfig(hidden_size=4, dropout=0),
        training_config=TrainingConfig(
            batch_size=16, num_workers=0, max_epochs=1, patience=1,
            seed=42, device="cpu"
        ),
    )

    run, manifest = orchestrator.run("BTC", ModelType.GRU, snapshot, 42)

    checkpoint = torch.load(run.directory / "model.pt", map_location="cpu", weights_only=True)
    best_checkpoint = torch.load(
        run.directory / "best_checkpoint.pt", map_location="cpu", weights_only=True
    )
    assert manifest["status"] in {"accepted", "rejected"}
    assert checkpoint["model_type"] == "gru"
    assert checkpoint["state_dict"]
    assert all(
        torch.equal(checkpoint["state_dict"][name], value)
        for name, value in best_checkpoint["state_dict"].items()
    )
    assert (run.directory / "best_checkpoint.pt").exists()
    assert (run.directory / "last_checkpoint.pt").exists()
    assert (run.directory / "scaler.json").exists()
    assert (run.directory / "target_scaler.json").exists()
    store.verify(run)


def test_v2_gru_training_derives_fused_feature_input_size(tmp_path):
    frames = []
    for symbol, multiplier in (("BTC", 1.0), ("ETH", 1.1), ("SOL", 0.9)):
        frame = candles(1200, "2024-01-01T00:00:00Z").copy()
        frame["symbol"] = symbol
        for column in ("open_price", "high_price", "low_price", "close_price"):
            frame[column] *= multiplier
        frames.append(frame)
    warehouse = pd.concat(frames, ignore_index=True)
    start = utc_datetime("2024-01-01T00:00:00Z")
    cutoff = utc_datetime("2024-02-20T00:00:00Z")
    config = ForecastDataConfig(
        symbols=("BTC",), source_code="binance", feature_version="hourly-return-v2",
        lookback_hours=336, horizon_hours=1,
        validation_start=utc_datetime("2024-02-05T00:00:00Z"),
        test_start=utc_datetime("2024-02-12T00:00:00Z"),
        history_start={"BTC": start},
        context_symbols=("BTC", "ETH", "SOL"),
    )
    snapshot = SnapshotBuilder(
        FakeRepository(warehouse), config, tmp_path / "snapshots"
    ).build("BTC", start, cutoff)
    store = ArtifactStore(tmp_path / "runs")
    orchestrator = TrainingOrchestrator(
        store,
        recurrent_config=RecurrentConfig(hidden_size=4, dropout=0),
        training_config=TrainingConfig(
            batch_size=32, num_workers=0, max_epochs=1, patience=1, seed=42,
            device="cpu", show_progress=False,
        ),
    )

    run, _ = orchestrator.run("BTC", ModelType.GRU, snapshot, 42)
    model_config = json.loads(
        (run.directory / "model_config.json").read_text(encoding="utf-8")
    )
    feature_names = json.loads(
        (run.directory / "feature_names.json").read_text(encoding="utf-8")
    )

    assert model_config["input_size"] == 81
    assert model_config["separate_direction_head"] is False
    assert model_config["quantile_output"] is True
    assert model_config["quantile_logistic_head"] is True
    assert len(feature_names["feature_names"]) == 81
