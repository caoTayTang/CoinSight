import numpy as np
import pandas as pd

from pipeline.decision.data.dataloader import ForecastDataModule
from pipeline.decision.evaluation.evaluator import (
    EvaluationReport,
    ModelEvaluator,
    compute_persistence_diagnostics,
)
from pipeline.decision.evaluation.metrics import (
    compute_direction_metrics,
    compute_metrics,
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
    assert report.training_majority_label == "up"
    assert report.majority_direction.predicted_up_rate == 1.0
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


def test_candidate_selection_uses_direction_not_mae():
    actual = np.asarray([-0.02, 0.01, -0.03, 0.04])
    predicted = np.asarray([-1.0, 1.0, -1.0, 1.0])
    majority = np.ones(len(actual))
    reference = np.full(len(actual), 100.0)
    zero_metrics = compute_metrics(actual, np.zeros(len(actual)), reference)
    monthly = pd.DataFrame({
        "sample_count": [20] * 6,
        "beats_majority_direction": [True] * 6,
    })
    report = EvaluationReport(
        split=DatasetSplit.VALIDATION,
        model=compute_metrics(actual, predicted, reference, zero_metrics.mae_return),
        zero_return=zero_metrics,
        rolling_mean=zero_metrics,
        monthly=monthly,
        predictions=pd.DataFrame(),
        model_direction=compute_direction_metrics(actual, predicted),
        majority_direction=compute_direction_metrics(actual, majority),
        training_majority_label="up",
    )

    assert report.model.mae_return > report.zero_return.mae_return
    decision = ModelEvaluator(minimum_month_samples=20).decide_candidate(report)

    assert decision.status == "accepted"
    assert decision.policy == "direction-v1"


def test_candidate_rejects_signal_that_only_matches_majority_baseline():
    actual = np.asarray([-0.02, 0.01, -0.03, 0.04])
    majority = np.ones(len(actual))
    reference = np.full(len(actual), 100.0)
    zero_metrics = compute_metrics(actual, np.zeros(len(actual)), reference)
    report = EvaluationReport(
        split=DatasetSplit.VALIDATION,
        model=compute_metrics(actual, majority, reference, zero_metrics.mae_return),
        zero_return=zero_metrics,
        rolling_mean=zero_metrics,
        monthly=pd.DataFrame({
            "sample_count": [20] * 6,
            "beats_majority_direction": [False] * 6,
        }),
        predictions=pd.DataFrame(),
        model_direction=compute_direction_metrics(actual, majority),
        majority_direction=compute_direction_metrics(actual, majority),
        training_majority_label="up",
    )

    decision = ModelEvaluator(minimum_month_samples=20).decide_candidate(report)

    assert decision.status == "rejected"
    assert "model_does_not_beat_train_majority_direction" in decision.reasons
