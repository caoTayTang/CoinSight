"""Chronological split assignment and expanding-window folds."""
from __future__ import annotations

from collections.abc import Iterator
import numpy as np
import pandas as pd

from pipeline.decision.types import DatasetSplit, SplitBoundaries, TimeFold


class TimeSeriesSplitter:
    def assign(self, samples: pd.DataFrame, boundaries: SplitBoundaries) -> pd.DataFrame:
        if "target_time" not in samples:
            raise ValueError("samples must contain target_time")
        frame = samples.copy()
        target = pd.to_datetime(frame["target_time"], utc=True)
        validation_start = pd.Timestamp(boundaries.validation_start)
        test_start = pd.Timestamp(boundaries.test_start)
        test_end = pd.Timestamp(boundaries.test_end)
        frame["split"] = np.select(
            [target < validation_start,
             (target >= validation_start) & (target < test_start),
             (target >= test_start) & (target < test_end)],
            [DatasetSplit.TRAIN.value, DatasetSplit.VALIDATION.value, DatasetSplit.TEST.value],
            default="out_of_scope",
        )
        self.validate_no_leakage(frame)
        return frame

    def validate_no_leakage(self, samples: pd.DataFrame) -> None:
        if samples["sample_id"].duplicated().any():
            raise ValueError("a sample_id appears more than once")
        scoped = samples[samples["split"].isin(item.value for item in DatasetSplit)]
        if scoped["target_time"].duplicated().any():
            raise ValueError("target_time values overlap between samples")
        for split in DatasetSplit:
            group = scoped[scoped["split"] == split.value]
            if not group.empty and not pd.to_datetime(group["target_time"], utc=True).is_monotonic_increasing:
                raise ValueError(f"{split.value} samples must be sorted by target_time")

    def expanding_folds(
        self,
        train_samples: pd.DataFrame,
        n_folds: int,
        gap_hours: int = 1,
        frequency: str = "1h",
    ) -> Iterator[TimeFold]:
        if n_folds < 1:
            raise ValueError("n_folds must be positive")
        if frequency not in {"1h", "1d"}:
            raise ValueError("frequency must be either 1h or 1d")
        step = pd.Timedelta(hours=1) if frequency == "1h" else pd.Timedelta(days=1)
        valid = train_samples[train_samples["is_valid"]].sort_values("target_time")
        times = pd.DatetimeIndex(pd.to_datetime(valid["target_time"], utc=True).unique())
        chunks = [chunk for chunk in np.array_split(times, n_folds + 1) if len(chunk)]
        if len(chunks) != n_folds + 1:
            raise ValueError("not enough training timestamps for requested folds")
        for index in range(1, len(chunks)):
            validation_start = chunks[index][0].to_pydatetime()
            validation_end = (chunks[index][-1] + step).to_pydatetime()
            train_end = (
                pd.Timestamp(validation_start) - step * gap_hours
            ).to_pydatetime()
            yield TimeFold(train_end, validation_start, validation_end)
