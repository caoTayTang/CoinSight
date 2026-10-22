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


def _correlation(left: np.ndarray, right: np.ndarray) -> float | None:
    if len(left) < 2 or np.std(left) == 0 or np.std(right) == 0:
        return None
    return float(np.corrcoef(left, right)[0, 1])


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
