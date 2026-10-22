import pytest

pytest.importorskip("pyarrow")
pytest.importorskip("xgboost")
pytest.importorskip("sklearn")

from pipeline.decision.artifacts.store import ArtifactStore
from pipeline.decision.config import ForecastDataConfig, XGBoostConfig
from pipeline.decision.data.snapshot import SnapshotBuilder
from pipeline.decision.training.run_training import TrainingOrchestrator
from pipeline.decision.types import ModelType, utc_datetime
from tests.decision.forecasting.helpers import candles


class FakeRepository:
    def __init__(self, frame):
        self.frame = frame

    def fetch_candles(self, symbol, start, end):
        return self.frame[(self.frame.open_time >= start) & (self.frame.open_time < end)].copy()

    def fetch_source_batch_ids(self, symbol, start, end):
        return [1]


def test_xgboost_training_orchestrator_writes_auditable_run(tmp_path):
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
        xgboost_config=XGBoostConfig(
            n_estimators=20, early_stopping_rounds=3, min_child_weight=1, n_jobs=1
        ),
    )

    run, manifest = orchestrator.run("BTC", ModelType.XGBOOST, snapshot, 42)

    assert manifest["status"] in {"accepted", "rejected"}
    assert (run.directory / "model.ubj").exists()
    assert (run.directory / "validation_metrics.json").exists()
    assert (run.directory / "validation_predictions.parquet").exists()
    store.verify(run)
