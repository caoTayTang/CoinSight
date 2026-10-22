"""Shared contracts for period-based return forecasting."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


class ModelType(str, Enum):
    XGBOOST = "xgboost"
    GRU = "gru"
    LSTM = "lstm"
    PATCHTST = "patchtst"
    ITRANSFORMER = "itransformer"

    @classmethod
    def parse(cls, value: str | ModelType) -> ModelType:
        if isinstance(value, cls):
            return value
        try:
            return cls(value.lower())
        except ValueError as error:
            supported = ", ".join(item.value for item in cls)
            raise ValueError(f"unsupported model type {value!r}; expected one of {supported}") from error

    @property
    def is_sequence(self) -> bool:
        return self is not ModelType.XGBOOST


class DatasetSplit(str, Enum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


def utc_datetime(value: str | datetime | pd.Timestamp) -> datetime:
    """Parse a timestamp and require/normalize UTC."""
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.to_pydatetime()


@dataclass(frozen=True)
class SplitBoundaries:
    validation_start: datetime
    test_start: datetime
    test_end: datetime

    def __post_init__(self) -> None:
        values = tuple(utc_datetime(value) for value in (
            self.validation_start, self.test_start, self.test_end
        ))
        if not values[0] < values[1] < values[2]:
            raise ValueError("split boundaries must satisfy validation_start < test_start < test_end")
        object.__setattr__(self, "validation_start", values[0])
        object.__setattr__(self, "test_start", values[1])
        object.__setattr__(self, "test_end", values[2])


@dataclass(frozen=True)
class TimeRange:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class TimeFold:
    train_end: datetime
    validation_start: datetime
    validation_end: datetime


@dataclass(frozen=True)
class TabularData:
    X: np.ndarray
    y: np.ndarray
    metadata: pd.DataFrame
    feature_names: tuple[str, ...]


@dataclass(frozen=True)
class DatasetSnapshot:
    snapshot_id: str
    symbol: str
    root: Path
    manifest: dict[str, Any]

    @property
    def directory(self) -> Path:
        return self.root / self.snapshot_id / self.symbol

    def read_candles(self) -> pd.DataFrame:
        return pd.read_parquet(self.directory / "candles.parquet")

    def read_features(self) -> pd.DataFrame:
        return pd.read_parquet(self.directory / "features.parquet")

    def read_samples(self) -> pd.DataFrame:
        return pd.read_parquet(self.directory / "samples.parquet")


@dataclass(frozen=True)
class TrainingResult:
    best_epoch: int | None
    best_validation_mae: float
    history: tuple[dict[str, float], ...]
    duration_seconds: float


@dataclass(frozen=True)
class PredictionResult:
    symbol: str
    target_time: datetime
    reference_close_usdt: float
    predicted_log_return: float
    predicted_close_usdt: float
    model_type: ModelType
    run_id: str
    direction_probability_up: float | None = None
    return_q10: float | None = None
    return_q50: float | None = None
    return_q90: float | None = None
    forecast_confidence: str | None = None
