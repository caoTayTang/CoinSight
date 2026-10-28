import numpy as np
import pytest

from pipeline.decision.evaluation.baselines import (
    predict_rolling_mean_return,
    predict_training_majority_direction,
    predict_zero_return,
)
from pipeline.decision.evaluation.metrics import (
    compute_direction_metrics,
    compute_metrics,
)


def test_baselines_and_metrics_are_exact_on_small_vectors():
    windows = np.zeros((2, 4, 1))
    windows[0, :, 0] = [1, 2, 3, 4]
    windows[1, :, 0] = [-1, -2, -3, -4]
    assert predict_zero_return(2).tolist() == [0, 0]
    assert predict_rolling_mean_return(windows, hours=2).tolist() == [3.5, -3.5]

    actual = np.asarray([0.01, -0.02])
    predicted = np.asarray([0.0, -0.01])
    metrics = compute_metrics(actual, predicted, np.asarray([100.0, 200.0]), persistence_mae=0.015)
    assert metrics.mae_return == pytest.approx(0.01)
    assert metrics.relative_mae == pytest.approx(2 / 3)
    assert metrics.directional_accuracy == 0.5


def test_relative_mae_is_none_when_persistence_is_perfect():
    metrics = compute_metrics(np.zeros(2), np.zeros(2), np.ones(2), persistence_mae=0)
    assert metrics.relative_mae is None


def test_training_majority_direction_does_not_inspect_evaluation_labels():
    prediction, label = predict_training_majority_direction(
        np.asarray([-0.02, -0.01, 0.03]), 4
    )

    assert label == "down"
    assert prediction.tolist() == [-1.0, -1.0, -1.0, -1.0]


def test_binary_direction_metrics_report_imbalance_and_skill():
    metrics = compute_direction_metrics(
        np.asarray([-0.02, -0.01, 0.01, 0.03]),
        np.asarray([-0.01, 0.01, 0.02, 0.04]),
    )

    assert metrics.accuracy == 0.75
    assert metrics.balanced_accuracy == 0.75
    assert metrics.actual_up_rate == 0.5
    assert metrics.predicted_up_rate == 0.75
    assert metrics.mcc > 0
