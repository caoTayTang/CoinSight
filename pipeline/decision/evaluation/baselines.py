"""Naive forecasts that every complex model must beat."""
from __future__ import annotations

import numpy as np


def predict_zero_return(n_samples: int) -> np.ndarray:
    if n_samples < 0:
        raise ValueError("n_samples cannot be negative")
    return np.zeros(n_samples, dtype=np.float64)


def predict_training_majority_direction(
    training_return: np.ndarray,
    n_samples: int,
) -> tuple[np.ndarray, str]:
    """Always predict the UP/DOWN class that is most common in training."""
    values = np.asarray(training_return, dtype=np.float64).reshape(-1)
    if not len(values) or not np.isfinite(values).all():
        raise ValueError("training returns must be non-empty and finite")
    if n_samples < 0:
        raise ValueError("n_samples cannot be negative")
    majority_is_up = float(np.mean(values > 0)) >= 0.5
    label = "up" if majority_is_up else "down"
    prediction = np.full(
        n_samples, 1.0 if majority_is_up else -1.0, dtype=np.float64
    )
    return prediction, label


def predict_rolling_mean_return(
    windows: np.ndarray, return_feature_index: int = 0, hours: int = 24
) -> np.ndarray:
    values = np.asarray(windows, dtype=np.float64)
    if values.ndim != 3:
        raise ValueError("windows must have shape [samples, time, features]")
    if hours <= 0 or hours > values.shape[1]:
        raise ValueError("hours must fit inside the sequence length")
    result = values[:, -hours:, return_feature_index].mean(axis=1)
    if not np.isfinite(result).all():
        raise ValueError("rolling baseline contains NaN or infinite values")
    return result
