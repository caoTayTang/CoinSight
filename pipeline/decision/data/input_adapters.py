"""Convert the canonical feature timeline into model-specific inputs."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from pipeline.decision.data.feature_extractor import (
    BASE_FEATURES,
    DAILY_SEQUENCE_FEATURES,
)
from pipeline.decision.data.scaler import SequenceScaler
from pipeline.decision.types import TabularData

LAG_SERIES = (
    "log_return_1h", "open_close_return", "high_low_range",
    "log_volume", "volume_change", "log_trade_count",
)
LAG_HOURS = (1, 2, 3, 6, 12, 24, 48, 72, 167)
MOMENTUM_HOURS = (6, 12, 24, 72, 168)
VOLATILITY_HOURS = (6, 24, 72, 168)
VOLUME_ZSCORE_HOURS = (24, 168)

DAILY_LAG_SERIES = (
    "log_return_1d", "open_close_return", "high_low_range",
    "log_volume", "volume_change", "log_trade_count",
)
DAILY_LAG_PERIODS = (1, 2, 3, 7, 14, 30, 60, 89)
DAILY_MOMENTUM_PERIODS = (7, 14, 30, 60, 90)
DAILY_VOLATILITY_PERIODS = (7, 14, 30, 60, 90)
DAILY_VOLUME_ZSCORE_PERIODS = (7, 30, 90)


@dataclass(frozen=True)
class SequenceArrays:
    X: np.ndarray
    y: np.ndarray
    metadata: pd.DataFrame


class XGBoostInputAdapter:
    def __init__(self, feature_version: str = "hourly-return-v1"):
        self.feature_version = feature_version
        if feature_version.startswith("hourly-"):
            self.current_features = BASE_FEATURES
            self.lag_series = LAG_SERIES
            self.lag_periods = LAG_HOURS
            self.momentum_periods = MOMENTUM_HOURS
            self.volatility_periods = VOLATILITY_HOURS
            self.volume_zscore_periods = VOLUME_ZSCORE_HOURS
            self.return_feature = "log_return_1h"
            suffix = "h"
        elif feature_version == "daily-return-v1":
            self.current_features = DAILY_SEQUENCE_FEATURES
            self.lag_series = DAILY_LAG_SERIES
            self.lag_periods = DAILY_LAG_PERIODS
            self.momentum_periods = DAILY_MOMENTUM_PERIODS
            self.volatility_periods = DAILY_VOLATILITY_PERIODS
            self.volume_zscore_periods = DAILY_VOLUME_ZSCORE_PERIODS
            self.return_feature = "log_return_1d"
            suffix = "d"
        else:
            raise ValueError(f"unsupported feature version: {feature_version}")
        self.period_suffix = suffix
        names = [f"{name}__lag0" for name in self.current_features]
        names.extend(
            f"{name}__lag{lag}" for name in self.lag_series
            for lag in self.lag_periods
        )
        names.extend(
            f"momentum_{period}{suffix}"
            for period in self.momentum_periods
        )
        names.extend(
            f"volatility_{period}{suffix}"
            for period in self.volatility_periods
        )
        names.extend(
            f"volume_zscore_{period}{suffix}"
            for period in self.volume_zscore_periods
        )
        self._feature_names = tuple(names)

    def feature_names(self) -> tuple[str, ...]:
        return self._feature_names

    def transform(self, features: pd.DataFrame, samples: pd.DataFrame) -> TabularData:
        valid = samples[samples["is_valid"]].sort_values("target_time").reset_index(drop=True)
        timeline = features.sort_values("row_number").reset_index(drop=True)
        matrix: list[list[float]] = []
        for sample in valid.itertuples(index=False):
            end = int(sample.window_end_row)
            row: list[float] = [
                float(timeline.at[end, name]) for name in self.current_features
            ]
            for name in self.lag_series:
                row.extend(
                    float(timeline.at[end - lag, name]) for lag in self.lag_periods
                )
            close = float(timeline.at[end, "close_price"])
            row.extend(
                float(np.log(close / float(timeline.at[end - period, "close_price"])))
                for period in self.momentum_periods
            )
            for period in self.volatility_periods:
                values = timeline.loc[
                    end - period + 1:end, self.return_feature
                ].to_numpy(dtype=float)
                row.append(float(values.std(ddof=0)))
            for period in self.volume_zscore_periods:
                values = timeline.loc[
                    end - period + 1:end, "log_volume"
                ].to_numpy(dtype=float)
                std = float(values.std(ddof=0))
                row.append(0.0 if std == 0 else float((values[-1] - values.mean()) / std))
            matrix.append(row)
        X = np.asarray(matrix, dtype=np.float32)
        if len(valid) == 0:
            X = np.empty((0, len(self._feature_names)), dtype=np.float32)
        if X.shape[1] != len(self._feature_names) or not np.isfinite(X).all():
            raise ValueError("XGBoost adapter produced invalid inputs")
        metadata = valid[[
            "sample_id", "symbol", "latest_input_open_time", "cutoff_time", "target_time",
            "reference_close_usdt", "actual_close_usdt",
        ]].reset_index(drop=True)
        return TabularData(
            X=X,
            y=valid["target_log_return"].to_numpy(dtype=np.float32),
            metadata=metadata,
            feature_names=self._feature_names,
        )


class SequenceInputAdapter:
    def __init__(
        self,
        features: pd.DataFrame,
        scaler: SequenceScaler | None = None,
        feature_names: tuple[str, ...] | None = None,
    ):
        self.scaler = scaler
        self.feature_names = (
            scaler.feature_names if scaler is not None
            else feature_names or BASE_FEATURES
        )
        timeline = features.sort_values("row_number").reset_index(drop=True)
        missing = set(self.feature_names) - set(timeline.columns)
        if missing:
            raise ValueError(f"sequence features are missing columns: {sorted(missing)}")
        values = timeline.loc[:, list(self.feature_names)].to_numpy(dtype=np.float64)
        if self.scaler is not None:
            if not self.scaler.is_fitted:
                raise RuntimeError("sequence scaler has not been fitted")
            values = (values - self.scaler.mean_) / self.scaler.scale_
        self._matrix = values.astype(np.float32, copy=False)

    def transform_rows(self, start: int, end: int) -> np.ndarray:
        window = self._matrix[start:end + 1]
        if window.shape != (end - start + 1, len(self.feature_names)):
            raise ValueError("sequence window has an unexpected shape")
        if not np.isfinite(window).all():
            raise ValueError("sequence window contains NaN or infinite values")
        return window

    def transform_one(self, sample: pd.Series) -> np.ndarray:
        start, end = int(sample["window_start_row"]), int(sample["window_end_row"])
        return self.transform_rows(start, end)

    def layout(self, window: np.ndarray) -> np.ndarray:
        return window


class PatchTSTInputAdapter(SequenceInputAdapter):
    def layout(self, window: np.ndarray) -> np.ndarray:
        return np.ascontiguousarray(window.T)
