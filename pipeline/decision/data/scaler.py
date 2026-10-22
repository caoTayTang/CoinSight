"""Serializable train-only standardization for sequence features and targets."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


class SequenceScaler:
    def __init__(self, feature_names: tuple[str, ...]):
        self.feature_names = feature_names
        self.mean_: np.ndarray | None = None
        self.scale_: np.ndarray | None = None

    def fit(self, train_features: np.ndarray) -> SequenceScaler:
        values = np.asarray(train_features, dtype=np.float64)
        if values.ndim != 2 or values.shape[1] != len(self.feature_names):
            raise ValueError("train_features must have shape [rows, feature_count]")
        if not np.isfinite(values).all():
            raise ValueError("cannot fit scaler on NaN or infinite values")
        self.mean_ = values.mean(axis=0)
        std = values.std(axis=0, ddof=0)
        self.scale_ = np.where(std == 0, 1.0, std)
        return self

    @property
    def is_fitted(self) -> bool:
        return self.mean_ is not None and self.scale_ is not None

    def transform(self, features: np.ndarray) -> np.ndarray:
        if not self.is_fitted:
            raise RuntimeError("scaler has not been fitted")
        values = np.asarray(features, dtype=np.float64)
        if values.shape[-1] != len(self.feature_names):
            raise ValueError("last dimension does not match feature_count")
        result = (values - self.mean_) / self.scale_
        if not np.isfinite(result).all():
            raise ValueError("scaled features contain NaN or infinite values")
        return result.astype(np.float32)

    def save(self, path: Path) -> None:
        if not self.is_fitted:
            raise RuntimeError("cannot save an unfitted scaler")
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "feature_names": list(self.feature_names),
            "mean": self.mean_.tolist(),
            "scale": self.scale_.tolist(),
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> SequenceScaler:
        payload = json.loads(path.read_text(encoding="utf-8"))
        scaler = cls(tuple(payload["feature_names"]))
        scaler.mean_ = np.asarray(payload["mean"], dtype=np.float64)
        scaler.scale_ = np.asarray(payload["scale"], dtype=np.float64)
        return scaler


class TargetScaler:
    """Standardize one regression target using training samples only."""

    def __init__(self):
        self.mean_: float | None = None
        self.scale_: float | None = None

    def fit(self, train_targets: np.ndarray) -> TargetScaler:
        values = np.asarray(train_targets, dtype=np.float64).reshape(-1)
        if not len(values) or not np.isfinite(values).all():
            raise ValueError("cannot fit target scaler on empty or non-finite values")
        self.mean_ = float(values.mean())
        std = float(values.std(ddof=0))
        self.scale_ = 1.0 if std == 0.0 else std
        return self

    @property
    def is_fitted(self) -> bool:
        return self.mean_ is not None and self.scale_ is not None

    def transform(self, targets: np.ndarray) -> np.ndarray:
        if not self.is_fitted:
            raise RuntimeError("target scaler has not been fitted")
        values = np.asarray(targets, dtype=np.float64)
        result = (values - self.mean_) / self.scale_
        if not np.isfinite(result).all():
            raise ValueError("scaled targets contain NaN or infinite values")
        return result.astype(np.float32)

    def inverse_transform(self, targets: np.ndarray) -> np.ndarray:
        if not self.is_fitted:
            raise RuntimeError("target scaler has not been fitted")
        values = np.asarray(targets, dtype=np.float64)
        result = values * self.scale_ + self.mean_
        if not np.isfinite(result).all():
            raise ValueError("inverse-scaled targets contain NaN or infinite values")
        return result

    def save(self, path: Path) -> None:
        if not self.is_fitted:
            raise RuntimeError("cannot save an unfitted target scaler")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "target": "target_log_return",
            "mean": self.mean_,
            "scale": self.scale_,
        }, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> TargetScaler:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("target") != "target_log_return":
            raise ValueError("unsupported target scaler artifact")
        scaler = cls()
        scaler.mean_ = float(payload["mean"])
        scaler.scale_ = float(payload["scale"])
        if scaler.scale_ <= 0:
            raise ValueError("target scaler scale must be positive")
        return scaler
