import numpy as np

from pipeline.decision.data.dataloader import ForecastDataModule
from pipeline.decision.evaluation.evaluator import (
    ModelEvaluator,
    compute_persistence_diagnostics,
)
from pipeline.decision.types import DatasetSplit, ModelType
from tests.decision.forecasting.test_dataloader import prepared_frames


def test_evaluator_aligns_model_and_baselines_on_same_samples():
    features, samples = prepared_frames()
    module = ForecastDataModule.from_frames(features, samples, ModelType.XGBOOST)
    module.setup()
    predicted = np.zeros(2)

    report = ModelEvaluator(minimum_month_samples=1).evaluate_predictions(
        predicted, module, DatasetSplit.VALIDATION
    )

    assert report.model.sample_count == 2
    assert report.zero_return.sample_count == 2
    assert report.rolling_mean.sample_count == 2
    assert report.persistence is not None
    assert report.predictions["sample_id"].tolist() == module.metadata(
        DatasetSplit.VALIDATION
    )["sample_id"].tolist()


def test_persistence_diagnostics_detect_copy_collapse():
    actual = np.asarray([-0.02, 0.01, 0.03, -0.01])
    predicted = np.asarray([-0.0001, 0.0001, 0.0001, -0.0001])

    diagnostics = compute_persistence_diagnostics(
        actual, predicted, copy_threshold=0.001
    )

    assert diagnostics.movement_scale_ratio < 0.01
    assert diagnostics.copy_rate == 1.0
    assert diagnostics.beat_persistence_rate == 1.0
