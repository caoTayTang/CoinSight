"""Evaluate predictions against identical samples and mandatory baselines."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from pipeline.decision.data.dataloader import ForecastDataModule
from pipeline.decision.evaluation.baselines import (
    predict_training_majority_direction,
    predict_zero_return,
)
from pipeline.decision.evaluation.metrics import (
    DirectionMetrics,
    ForecastMetrics,
    compute_direction_metrics,
    compute_metrics,
)
from pipeline.decision.types import DatasetSplit


@dataclass(frozen=True)
class CandidateDecision:
    status: str
    reasons: tuple[str, ...]
    policy: str = "direction-v1"


@dataclass(frozen=True)
class PersistenceDiagnostics:
    sample_count: int
    mean_abs_actual_move: float
    mean_abs_predicted_move: float
    movement_scale_ratio: float | None
    copy_threshold: float
    copy_rate: float
    beat_persistence_rate: float

    def to_dict(self) -> dict:
        return asdict(self)


def compute_persistence_diagnostics(
    actual_return: np.ndarray,
    predicted_return: np.ndarray,
    *,
    copy_threshold: float = 0.001,
) -> PersistenceDiagnostics:
    actual = np.asarray(actual_return, dtype=np.float64).reshape(-1)
    predicted = np.asarray(predicted_return, dtype=np.float64).reshape(-1)
    if not len(actual) or len(actual) != len(predicted):
        raise ValueError("persistence diagnostics require equal non-empty arrays")
    if not np.isfinite(actual).all() or not np.isfinite(predicted).all():
        raise ValueError("persistence diagnostics cannot contain non-finite values")
    if not np.isfinite(copy_threshold) or copy_threshold < 0:
        raise ValueError("copy_threshold must be non-negative")
    actual_move = np.abs(np.expm1(actual))
    predicted_move = np.abs(np.expm1(predicted))
    mean_actual = float(np.mean(actual_move))
    mean_predicted = float(np.mean(predicted_move))
    ratio = None if mean_actual == 0 else mean_predicted / mean_actual
    return PersistenceDiagnostics(
        sample_count=len(actual),
        mean_abs_actual_move=mean_actual,
        mean_abs_predicted_move=mean_predicted,
        movement_scale_ratio=ratio,
        copy_threshold=float(copy_threshold),
        copy_rate=float(np.mean(predicted_move < copy_threshold)),
        beat_persistence_rate=float(
            np.mean(np.abs(predicted - actual) < np.abs(actual))
        ),
    )


@dataclass(frozen=True)
class EvaluationReport:
    split: DatasetSplit
    model: ForecastMetrics
    zero_return: ForecastMetrics
    rolling_mean: ForecastMetrics
    monthly: pd.DataFrame
    predictions: pd.DataFrame
    persistence: PersistenceDiagnostics | None = None
    model_direction: DirectionMetrics | None = None
    majority_direction: DirectionMetrics | None = None
    training_majority_label: str | None = None


class ModelEvaluator:
    def __init__(
        self,
        rolling_periods: int = 24,
        minimum_month_samples: int = 500,
        copy_return_threshold: float = 0.001,
    ):
        self.rolling_periods = rolling_periods
        self.minimum_month_samples = minimum_month_samples
        if not np.isfinite(copy_return_threshold) or copy_return_threshold < 0:
            raise ValueError("copy_return_threshold must be non-negative")
        self.copy_return_threshold = float(copy_return_threshold)

    def evaluate_predictions(
        self,
        predicted_return: np.ndarray,
        data: ForecastDataModule,
        split: DatasetSplit | str,
    ) -> EvaluationReport:
        resolved = DatasetSplit(split)
        actual = data.targets(resolved).astype(np.float64)
        training_actual = data.targets(DatasetSplit.TRAIN).astype(np.float64)
        predicted = np.asarray(predicted_return, dtype=np.float64).reshape(-1)
        metadata = data.metadata(resolved)
        if len(predicted) != len(actual):
            raise ValueError("prediction count does not match evaluation samples")
        zero = predict_zero_return(len(actual))
        rolling = data.rolling_mean_return(resolved, self.rolling_periods)
        majority, majority_label = predict_training_majority_direction(
            training_actual, len(actual)
        )
        reference = metadata["reference_close_usdt"].to_numpy(dtype=np.float64)
        zero_metrics = compute_metrics(actual, zero, reference)
        model_metrics = compute_metrics(actual, predicted, reference, zero_metrics.mae_return)
        rolling_metrics = compute_metrics(actual, rolling, reference, zero_metrics.mae_return)
        predictions = metadata.copy()
        predictions["actual_log_return"] = actual
        predictions["predicted_log_return"] = predicted
        predictions["zero_return_prediction"] = zero
        predictions["rolling_mean_prediction"] = rolling
        predictions["majority_direction_prediction"] = majority
        predictions["predicted_close_usdt"] = reference * np.exp(predicted)
        persistence = compute_persistence_diagnostics(
            actual,
            predicted,
            copy_threshold=self.copy_return_threshold,
        )
        monthly = self.evaluate_by_month(predictions)
        return EvaluationReport(
            resolved,
            model_metrics,
            zero_metrics,
            rolling_metrics,
            monthly,
            predictions,
            persistence,
            compute_direction_metrics(actual, predicted),
            compute_direction_metrics(actual, majority),
            majority_label,
        )

    def evaluate(
        self,
        model,
        data: ForecastDataModule,
        split: DatasetSplit | str,
        predict_fn: Callable | None = None,
    ) -> EvaluationReport:
        resolved = DatasetSplit(split)
        if predict_fn is not None:
            predicted = predict_fn(model, data, resolved)
        elif data.model_type.value == "xgboost":
            predicted = model.predict(data.tabular(resolved))
        else:
            raise ValueError("sequence models require a predict_fn from TorchTrainer")
        return self.evaluate_predictions(predicted, data, resolved)

    def evaluate_by_month(self, predictions: pd.DataFrame) -> pd.DataFrame:
        rows = []
        frame = predictions.copy()
        frame["month"] = pd.to_datetime(frame["target_time"], utc=True).dt.strftime("%Y-%m")
        for month, group in frame.groupby("month", sort=True):
            actual = group["actual_log_return"].to_numpy()
            reference = group["reference_close_usdt"].to_numpy()
            zero = compute_metrics(actual, group["zero_return_prediction"].to_numpy(), reference)
            model = compute_metrics(
                actual, group["predicted_log_return"].to_numpy(), reference, zero.mae_return
            )
            rolling = compute_metrics(
                actual, group["rolling_mean_prediction"].to_numpy(), reference, zero.mae_return
            )
            persistence = compute_persistence_diagnostics(
                actual,
                group["predicted_log_return"].to_numpy(),
                copy_threshold=self.copy_return_threshold,
            )
            model_direction = compute_direction_metrics(
                actual, group["predicted_log_return"].to_numpy()
            )
            majority_direction = compute_direction_metrics(
                actual, group["majority_direction_prediction"].to_numpy()
            )
            rows.append({
                "month": month,
                "sample_count": len(group),
                "model_mae": model.mae_return,
                "zero_return_mae": zero.mae_return,
                "rolling_mean_mae": rolling.mae_return,
                "beats_zero_return": model.mae_return < zero.mae_return,
                "beats_rolling_mean": model.mae_return < rolling.mae_return,
                "model_direction_accuracy": model_direction.accuracy,
                "model_balanced_accuracy": model_direction.balanced_accuracy,
                "model_mcc": model_direction.mcc,
                "majority_direction_accuracy": majority_direction.accuracy,
                "beats_majority_direction": (
                    model_direction.accuracy > majority_direction.accuracy
                ),
                "movement_scale_ratio": persistence.movement_scale_ratio,
                "copy_rate": persistence.copy_rate,
                "beat_persistence_rate": persistence.beat_persistence_rate,
            })
        return pd.DataFrame(rows)

    def decide_candidate(self, report: EvaluationReport) -> CandidateDecision:
        if report.split is not DatasetSplit.VALIDATION:
            raise ValueError("candidate decisions must use validation, never test")
        reasons = []
        if report.model_direction is None or report.majority_direction is None:
            raise ValueError("candidate decisions require binary direction metrics")
        if report.model_direction.accuracy <= report.majority_direction.accuracy:
            reasons.append("model_does_not_beat_train_majority_direction")
        if report.model_direction.balanced_accuracy <= 0.5:
            reasons.append("model_balanced_accuracy_not_above_chance")
        eligible = report.monthly[
            report.monthly["sample_count"] >= self.minimum_month_samples
        ]
        if len(eligible) < 6:
            reasons.append("insufficient_monthly_coverage")
        else:
            required_wins = len(eligible) // 2 + 1
            if int(eligible["beats_majority_direction"].sum()) < required_wins:
                reasons.append(
                    "model_does_not_beat_majority_direction_in_most_months"
                )
        return CandidateDecision("accepted" if not reasons else "rejected", tuple(reasons))
