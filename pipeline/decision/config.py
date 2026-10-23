"""Validated configuration objects for period-based return forecasting."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pipeline.decision.types import SplitBoundaries, utc_datetime
from pipeline.settings import FORECAST_RUN_DIR, FORECAST_SNAPSHOT_DIR, FORECASTING


@dataclass(frozen=True)
class ForecastDataConfig:
    symbols: tuple[str, ...]
    source_code: str
    feature_version: str
    lookback_hours: int
    horizon_hours: int
    validation_start: datetime
    test_start: datetime
    history_start: dict[str, datetime]
    context_symbols: tuple[str, ...] = ()
    rolling_baseline_hours: int = 24
    frequency: str = "1h"
    minimum_month_samples: int = 500

    def __post_init__(self) -> None:
        if not self.symbols:
            raise ValueError("at least one forecast symbol is required")
        if self.frequency not in {"1h", "1d"}:
            raise ValueError("frequency must be either 1h or 1d")
        if self.lookback_hours <= 1:
            raise ValueError("lookback_periods must be greater than one")
        if self.horizon_hours <= 0:
            raise ValueError("horizon_periods must be positive")
        expected_prefix = "hourly-" if self.frequency == "1h" else "daily-"
        if not self.feature_version.startswith(expected_prefix):
            raise ValueError("feature_version does not match frequency")
        if self.rolling_baseline_hours <= 0:
            raise ValueError("rolling_baseline_periods must be positive")
        if self.minimum_month_samples <= 0:
            raise ValueError("minimum_month_samples must be positive")
        if self.validation_start >= self.test_start:
            raise ValueError("validation_start must be before test_start")
        missing = set(self.symbols) - set(self.history_start)
        if missing:
            raise ValueError(f"history_start is missing symbols: {sorted(missing)}")
        if self.feature_version in {"hourly-return-v2", "daily-return-v2"}:
            if not self.context_symbols:
                raise ValueError(
                    f"{self.feature_version} requires at least the target symbol"
                )
            missing_targets = set(self.symbols) - set(self.context_symbols)
            if missing_targets:
                raise ValueError(
                    "context_symbols must include every forecast symbol: "
                    f"{sorted(missing_targets)}"
                )

    def boundaries(self, test_end: datetime) -> SplitBoundaries:
        return SplitBoundaries(self.validation_start, self.test_start, test_end)

    # Compatibility aliases keep old hourly snapshots/tests readable while the
    # pipeline uses period-neutral terminology from this point onward.
    @property
    def lookback_periods(self) -> int:
        return self.lookback_hours

    @property
    def horizon_periods(self) -> int:
        return self.horizon_hours

    @property
    def rolling_baseline_periods(self) -> int:
        return self.rolling_baseline_hours

    @property
    def period_delta(self):
        import pandas as pd

        return pd.Timedelta(hours=1) if self.frequency == "1h" else pd.Timedelta(days=1)


@dataclass(frozen=True)
class XGBoostConfig:
    objective: str = "reg:squarederror"
    eval_metric: str = "mae"
    tree_method: str = "hist"
    n_estimators: int = 400
    learning_rate: float = 0.03
    max_depth: int = 3
    min_child_weight: int = 20
    subsample: float = 0.8
    colsample_bytree: float = 0.8
    reg_alpha: float = 0.0
    reg_lambda: float = 10.0
    early_stopping_rounds: int = 30
    random_state: int = 42
    n_jobs: int = 2
    verbose_eval: int = 10


@dataclass(frozen=True)
class RecurrentConfig:
    input_size: int = 13
    hidden_size: int = 64
    num_layers: int = 1
    dropout: float = 0.3
    separate_direction_head: bool = False
    quantile_output: bool = True
    quantile_logistic_head: bool = True

    def __post_init__(self) -> None:
        if self.quantile_output and self.separate_direction_head:
            raise ValueError(
                "quantile output replaces the auxiliary direction head"
            )
        if self.quantile_logistic_head and not self.quantile_output:
            raise ValueError(
                "quantile logistic head requires quantile output"
            )


def recurrent_config_from_artifact(payload: dict) -> RecurrentConfig:
    """Keep historical scalar/two-head recurrent checkpoints loadable."""
    values = dict(payload)
    values.setdefault("separate_direction_head", False)
    values.setdefault("quantile_output", False)
    values.setdefault("quantile_logistic_head", False)
    return RecurrentConfig(**values)


@dataclass(frozen=True)
class TrainingConfig:
    batch_size: int = 256
    num_workers: int = 4
    pin_memory: bool = True
    max_epochs: int = 100
    learning_rate: float = 1e-3
    weight_decay: float = 1e-4
    patience: int = 10
    gradient_clip_norm: float = 3.0
    direction_loss_weight: float = 1.0
    persistence_loss_weight: float = 1.1
    persistence_margin_fraction: float = 0.25
    minimum_actual_move: float = 0.001
    seed: int = 42
    device: str = "cuda"
    show_progress: bool = True
    progress_every_batches: int = 10

    def __post_init__(self) -> None:
        if self.batch_size <= 0 or self.max_epochs <= 0:
            raise ValueError("batch_size and max_epochs must be positive")
        if self.num_workers < 0:
            raise ValueError("num_workers must be non-negative")
        if self.patience <= 0:
            raise ValueError("patience must be positive")
        if self.progress_every_batches <= 0:
            raise ValueError("progress_every_batches must be positive")
        if not math.isfinite(self.direction_loss_weight) or self.direction_loss_weight < 0:
            raise ValueError("direction_loss_weight must be non-negative")
        if (
            not math.isfinite(self.persistence_loss_weight)
            or self.persistence_loss_weight < 0
        ):
            raise ValueError("persistence_loss_weight must be non-negative")
        if (
            not math.isfinite(self.persistence_margin_fraction)
            or not 0 <= self.persistence_margin_fraction <= 1
        ):
            raise ValueError("persistence_margin_fraction must be in [0, 1]")
        if not math.isfinite(self.minimum_actual_move) or self.minimum_actual_move < 0:
            raise ValueError("minimum_actual_move must be non-negative")


def training_config_from_artifact(payload: dict) -> TrainingConfig:
    """Load config without enabling the new loss for historical checkpoints."""
    values = dict(payload)
    values.setdefault("direction_loss_weight", 0.0)
    if "persistence_loss_weight" not in values:
        values["persistence_loss_weight"] = 0.0
    values.setdefault("persistence_margin_fraction", 0.25)
    values.setdefault("minimum_actual_move", 0.001)
    return TrainingConfig(**values)


@dataclass(frozen=True)
class ArtifactConfig:
    snapshot_root: Path = field(default_factory=lambda: Path(FORECAST_SNAPSHOT_DIR))
    run_root: Path = field(default_factory=lambda: Path(FORECAST_RUN_DIR))


def load_forecast_data_config() -> ForecastDataConfig:
    frequency = str(FORECASTING.get("frequency", "1h"))
    return ForecastDataConfig(
        symbols=tuple(str(value).upper() for value in FORECASTING["symbols"]),
        source_code=str(FORECASTING["source_code"]),
        feature_version=str(FORECASTING["feature_version"]),
        lookback_hours=int(FORECASTING.get(
            "lookback_periods", FORECASTING.get("lookback_hours", 168)
        )),
        horizon_hours=int(FORECASTING.get(
            "horizon_periods", FORECASTING.get("horizon_hours", 1)
        )),
        validation_start=utc_datetime(FORECASTING["validation_start"]),
        test_start=utc_datetime(FORECASTING["test_start"]),
        history_start={
            str(symbol).upper(): utc_datetime(value)
            for symbol, value in FORECASTING["history_start"].items()
        },
        context_symbols=tuple(
            str(value).upper()
            for value in FORECASTING.get("context_symbols", FORECASTING["symbols"])
        ),
        rolling_baseline_hours=int(FORECASTING.get(
            "rolling_baseline_periods", FORECASTING.get("rolling_baseline_hours", 24)
        )),
        frequency=frequency,
        minimum_month_samples=int(FORECASTING.get(
            "minimum_month_samples", 500 if frequency == "1h" else 20
        )),
    )


def last_closed_hour(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    value = utc_datetime(now)
    return value.replace(minute=0, second=0, microsecond=0)


def last_closed_period(frequency: str, now: datetime | None = None) -> datetime:
    """Return the exclusive cutoff after the latest fully closed candle."""
    value = utc_datetime(now or datetime.now(UTC))
    if frequency == "1h":
        return value.replace(minute=0, second=0, microsecond=0)
    if frequency == "1d":
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    raise ValueError(f"unsupported forecasting frequency: {frequency}")
