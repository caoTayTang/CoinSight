"""Forecast metrics shared by model and baseline reports."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ForecastMetrics:
    sample_count: int
    mae_return: float
    rmse_return: float
    mae_price_usdt: float
    smape_price: float
    relative_mae: float | None
    directional_accuracy: float
    pearson: float | None
    spearman: float | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class DirectionMetrics:
    """Binary UP/DOWN metrics; zero return is treated as DOWN."""

    sample_count: int
    accuracy: float
    balanced_accuracy: float
    precision_up: float | None
    recall_up: float | None
    recall_down: float | None
    f1_up: float | None
    mcc: float
    actual_up_rate: float
    actual_down_rate: float
    predicted_up_rate: float

    def to_dict(self) -> dict:
        return asdict(self)


def _correlation(left: np.ndarray, right: np.ndarray) -> float | None:
    if len(left) < 2 or np.std(left) == 0 or np.std(right) == 0:
        return None
    return float(np.corrcoef(left, right)[0, 1])


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def compute_direction_metrics(
    actual_return: np.ndarray,
    predicted_return: np.ndarray,
) -> DirectionMetrics:
    """Evaluate return signs as a binary trading-direction signal."""
    actual = np.asarray(actual_return, dtype=np.float64).reshape(-1)
    predicted = np.asarray(predicted_return, dtype=np.float64).reshape(-1)
    if not len(actual) or len(actual) != len(predicted):
        raise ValueError("direction metric inputs must be non-empty and have equal lengths")
    if not np.isfinite(actual).all() or not np.isfinite(predicted).all():
        raise ValueError("direction metric inputs cannot contain NaN or infinite values")

    actual_up = actual > 0
    predicted_up = predicted > 0
    tp = int((actual_up & predicted_up).sum())
    tn = int((~actual_up & ~predicted_up).sum())
    fp = int((~actual_up & predicted_up).sum())
    fn = int((actual_up & ~predicted_up).sum())
    precision_up = _safe_ratio(tp, tp + fp)
    recall_up = _safe_ratio(tp, tp + fn)
    recall_down = _safe_ratio(tn, tn + fp)
    recalls = [value for value in (recall_down, recall_up) if value is not None]
    balanced_accuracy = float(np.mean(recalls))
    f1_up = (
        None
        if precision_up is None or recall_up is None or precision_up + recall_up == 0
        else 2 * precision_up * recall_up / (precision_up + recall_up)
    )
    denominator = float(
        np.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    )
    mcc = 0.0 if denominator == 0 else (tp * tn - fp * fn) / denominator
    return DirectionMetrics(
        sample_count=len(actual),
        accuracy=(tp + tn) / len(actual),
        balanced_accuracy=balanced_accuracy,
        precision_up=precision_up,
        recall_up=recall_up,
        recall_down=recall_down,
        f1_up=f1_up,
        mcc=float(mcc),
        actual_up_rate=float(actual_up.mean()),
        actual_down_rate=float((~actual_up).mean()),
        predicted_up_rate=float(predicted_up.mean()),
    )


def compute_metrics(
    actual_return: np.ndarray,
    predicted_return: np.ndarray,
    reference_close: np.ndarray,
    persistence_mae: float | None = None,
) -> ForecastMetrics:
    actual = np.asarray(actual_return, dtype=np.float64).reshape(-1)
    predicted = np.asarray(predicted_return, dtype=np.float64).reshape(-1)
    reference = np.asarray(reference_close, dtype=np.float64).reshape(-1)
    if not len(actual) or not (len(actual) == len(predicted) == len(reference)):
        raise ValueError("metric inputs must be non-empty and have equal lengths")
    if not all(np.isfinite(value).all() for value in (actual, predicted, reference)):
        raise ValueError("metric inputs cannot contain NaN or infinite values")
    if (reference <= 0).any():
        raise ValueError("reference prices must be positive")

    error = predicted - actual
    mae = float(np.mean(np.abs(error)))
    actual_price = reference * np.exp(actual)
    predicted_price = reference * np.exp(predicted)
    price_denominator = np.abs(actual_price) + np.abs(predicted_price)
    smape = float(np.mean(np.where(
        price_denominator == 0, 0.0,
        2 * np.abs(predicted_price - actual_price) / price_denominator,
    )))
    relative = None
    if persistence_mae is not None and persistence_mae > 0:
        relative = mae / persistence_mae
    actual_sign = np.sign(actual)
    predicted_sign = np.sign(predicted)
    ranked_actual = pd.Series(actual).rank(method="average").to_numpy()
    ranked_predicted = pd.Series(predicted).rank(method="average").to_numpy()
    return ForecastMetrics(
        sample_count=len(actual),
        mae_return=mae,
        rmse_return=float(np.sqrt(np.mean(error ** 2))),
        mae_price_usdt=float(np.mean(np.abs(predicted_price - actual_price))),
        smape_price=smape,
        relative_mae=relative,
        directional_accuracy=float(np.mean(actual_sign == predicted_sign)),
        pearson=_correlation(actual, predicted),
        spearman=_correlation(ranked_actual, ranked_predicted),
    )
