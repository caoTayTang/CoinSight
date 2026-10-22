"""One model-aware loader backed by a common snapshot and sample index."""
from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.decision.data.feature_extractor import (
    fused_symbols_from_feature_names,
    is_fused_feature_version,
    return_feature_name,
    sequence_feature_names,
)
from pipeline.decision.data.input_adapters import (
    PatchTSTInputAdapter,
    SequenceInputAdapter,
    XGBoostInputAdapter,
)
from pipeline.decision.data.scaler import SequenceScaler, TargetScaler
from pipeline.decision.types import (
    DatasetSnapshot,
    DatasetSplit,
    ModelType,
    TabularData,
)


class SequenceWindowDataset:
    def __init__(
        self,
        samples: pd.DataFrame,
        adapter: SequenceInputAdapter,
        target_scaler: TargetScaler | None = None,
        feature_version: str | None = None,
    ):
        self.samples = samples[samples["is_valid"]].sort_values("target_time").reset_index(drop=True)
        self.adapter = adapter
        self.target_scaler = target_scaler
        self._window_starts = self.samples["window_start_row"].to_numpy(dtype=np.int64)
        self._window_ends = self.samples["window_end_row"].to_numpy(dtype=np.int64)
        targets = self.samples["target_log_return"].to_numpy(dtype=np.float64)
        if self.target_scaler is not None:
            targets = self.target_scaler.transform(targets)
        self._targets = targets.astype(np.float32, copy=False)

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int) -> tuple[np.ndarray, np.ndarray]:
        start = int(self._window_starts[index])
        end = int(self._window_ends[index])
        window = self.adapter.layout(self.adapter.transform_rows(start, end))
        target = np.asarray([self._targets[index]], dtype=np.float32)
        return window, target


class ForecastDataModule:
    def __init__(
        self,
        snapshot: DatasetSnapshot | None,
        model_type: ModelType | str,
        batch_size: int = 128,
        seed: int = 42,
        num_workers: int = 0,
        pin_memory: bool = False,
        *,
        features: pd.DataFrame | None = None,
        samples: pd.DataFrame | None = None,
        scale_targets: bool = True,
        target_scaler: TargetScaler | None = None,
        feature_version: str | None = None,
        sequence_features: tuple[str, ...] | None = None,
    ):
        self.snapshot = snapshot
        self.model_type = ModelType.parse(model_type)
        self.batch_size = batch_size
        self.seed = seed
        self.num_workers = num_workers
        self.pin_memory = pin_memory
        self._features = features
        self._samples = samples
        self.scale_targets = scale_targets
        self._provided_target_scaler = target_scaler
        self.feature_version = feature_version or (
            snapshot.manifest.get("feature_version", "hourly-return-v1")
            if snapshot is not None else "hourly-return-v1"
        )
        self.sequence_feature_names = sequence_features or ()
        self.scaler: SequenceScaler | None = None
        self.target_scaler: TargetScaler | None = None
        self._tabular: dict[DatasetSplit, TabularData] = {}
        self._datasets: dict[DatasetSplit, SequenceWindowDataset] = {}

    @classmethod
    def from_frames(
        cls,
        features: pd.DataFrame,
        samples: pd.DataFrame,
        model_type: ModelType | str,
        batch_size: int = 128,
        seed: int = 42,
        scale_targets: bool = True,
        feature_version: str = "hourly-return-v1",
        sequence_features: tuple[str, ...] | None = None,
        *,
        num_workers: int = 0,
        pin_memory: bool = False,
    ) -> ForecastDataModule:
        return cls(
            None, model_type, batch_size, seed, num_workers, pin_memory,
            features=features, samples=samples,
            scale_targets=scale_targets, feature_version=feature_version,
            sequence_features=sequence_features,
        )

    def setup(self) -> None:
        if self._features is None or self._samples is None:
            if self.snapshot is None:
                raise ValueError("snapshot or in-memory frames are required")
            self._features = self.snapshot.read_features()
            self._samples = self.snapshot.read_samples()
        self._features = self._features.sort_values(["symbol", "row_number"]).reset_index(drop=True)
        self._samples = self._samples.sort_values("target_time").reset_index(drop=True)
        symbols = set(self._samples["symbol"].astype(str).str.upper())
        if len(symbols) != 1:
            raise ValueError("one ForecastDataModule must contain exactly one symbol")
        valid_splits = set(self._samples.loc[self._samples["is_valid"], "split"].unique())
        missing = {item.value for item in DatasetSplit} - valid_splits
        if missing:
            raise ValueError(f"snapshot is missing valid dataset splits: {sorted(missing)}")

        if self.model_type is ModelType.XGBOOST:
            if is_fused_feature_version(self.feature_version):
                raise ValueError(
                    f"{self.feature_version} multi-asset inputs are currently "
                    "supported by sequence models only"
                )
            adapter = XGBoostInputAdapter(self.feature_version)
            for split in DatasetSplit:
                rows = self._samples[self._samples["split"] == split.value]
                self._tabular[split] = adapter.transform(self._features, rows)
            return

        if not self.sequence_feature_names:
            if not is_fused_feature_version(self.feature_version):
                self.sequence_feature_names = sequence_feature_names(self.feature_version)
            elif self.snapshot is not None:
                stored = tuple(self.snapshot.manifest.get("sequence_feature_names", ()))
                if not stored:
                    raise ValueError(
                        f"{self.feature_version} snapshot has no fused feature layout; "
                        "build a new snapshot"
                    )
                fused_symbols_from_feature_names(stored, self.feature_version)
                self.sequence_feature_names = stored
            else:
                candidates = tuple(
                    str(column) for column in self._features.columns if "__" in str(column)
                )
                fused_symbols_from_feature_names(candidates, self.feature_version)
                self.sequence_feature_names = candidates

        train = self._samples[
            (self._samples["split"] == DatasetSplit.TRAIN.value) & self._samples["is_valid"]
        ]
        if train.empty:
            raise ValueError("cannot fit sequence scaler without valid training samples")
        used_rows: set[int] = set()
        for row in train.itertuples(index=False):
            used_rows.update(range(int(row.window_start_row), int(row.window_end_row) + 1))
        train_features = self._features.loc[
            sorted(used_rows), list(self.sequence_feature_names)
        ].to_numpy(dtype=np.float64)
        self.scaler = SequenceScaler(self.sequence_feature_names).fit(train_features)
        if self.scale_targets:
            self.target_scaler = self._provided_target_scaler or TargetScaler().fit(
                train["target_log_return"].to_numpy(dtype=np.float64)
            )
        adapter_class = PatchTSTInputAdapter if self.model_type is ModelType.PATCHTST else SequenceInputAdapter
        adapter = adapter_class(
            self._features, self.scaler, self.sequence_feature_names
        )
        for split in DatasetSplit:
            rows = self._samples[self._samples["split"] == split.value]
            self._datasets[split] = SequenceWindowDataset(
                rows, adapter, self.target_scaler
            )

    def _require_setup(self) -> None:
        if not self._tabular and not self._datasets:
            raise RuntimeError("call setup() before reading model data")

    def tabular(self, split: DatasetSplit | str) -> TabularData:
        self._require_setup()
        if self.model_type is not ModelType.XGBOOST:
            raise TypeError(f"{self.model_type.value} uses dataloader(), not tabular()")
        return self._tabular[DatasetSplit(split)]

    def dataset(self, split: DatasetSplit | str) -> SequenceWindowDataset:
        self._require_setup()
        if self.model_type is ModelType.XGBOOST:
            raise TypeError("xgboost uses tabular(), not dataset()")
        return self._datasets[DatasetSplit(split)]

    def dataloader(self, split: DatasetSplit | str, shuffle: bool | None = None):
        if self.model_type is ModelType.XGBOOST:
            raise TypeError("xgboost uses tabular(), not dataloader()")
        try:
            import torch
            from torch.utils.data import DataLoader
        except ImportError as error:
            raise RuntimeError("PyTorch is required for sequence dataloaders") from error
        resolved = DatasetSplit(split)
        should_shuffle = resolved is DatasetSplit.TRAIN if shuffle is None else shuffle
        generator = torch.Generator().manual_seed(self.seed)
        return DataLoader(
            self.dataset(resolved), batch_size=self.batch_size, shuffle=should_shuffle,
            drop_last=False, num_workers=self.num_workers, generator=generator,
            pin_memory=self.pin_memory,
            persistent_workers=self.num_workers > 0,
        )

    def raw_sequence(self, split: DatasetSplit | str) -> np.ndarray:
        """Unscaled time-major windows for baselines and parity checks."""
        self._require_setup()
        rows = self._samples[
            (self._samples["split"] == DatasetSplit(split).value) & self._samples["is_valid"]
        ].sort_values("target_time")
        adapter = SequenceInputAdapter(
            self._features, scaler=None, feature_names=self.sequence_feature_names
        )
        if rows.empty:
            return np.empty(
                (0, 0, len(self.sequence_feature_names)), dtype=np.float32
            )
        return np.stack([adapter.transform_one(row) for _, row in rows.iterrows()])

    def rolling_mean_return(
        self, split: DatasetSplit | str, periods: int
    ) -> np.ndarray:
        """Compute the target-coin baseline without materializing full windows."""
        self._require_setup()
        if periods <= 0:
            raise ValueError("periods must be positive")
        rows = self._samples[
            (self._samples["split"] == DatasetSplit(split).value)
            & self._samples["is_valid"]
        ].sort_values("target_time")
        if rows.empty:
            return np.empty(0, dtype=np.float64)
        starts = rows["window_start_row"].to_numpy(dtype=np.int64)
        ends = rows["window_end_row"].to_numpy(dtype=np.int64)
        if np.any(ends - starts + 1 < periods):
            raise ValueError("periods must fit inside every sequence window")
        offsets = np.arange(periods - 1, -1, -1, dtype=np.int64)
        indices = ends[:, None] - offsets[None, :]
        returns = self._features[
            return_feature_name(self.feature_version)
        ].to_numpy(dtype=np.float64)
        values = returns[indices]
        result = values.mean(axis=1)
        if not np.isfinite(result).all():
            raise ValueError("rolling baseline contains NaN or infinite values")
        return result

    def targets(self, split: DatasetSplit | str) -> np.ndarray:
        metadata = self.metadata(split)
        rows = self._samples.set_index("sample_id").loc[metadata["sample_id"]]
        return rows["target_log_return"].to_numpy(dtype=np.float32)

    def metadata(self, split: DatasetSplit | str) -> pd.DataFrame:
        self._require_setup()
        resolved = DatasetSplit(split)
        rows = self._samples[
            (self._samples["split"] == resolved.value) & self._samples["is_valid"]
        ].sort_values("target_time")
        return rows[[
            "sample_id", "symbol", "latest_input_open_time", "cutoff_time", "target_time",
            "reference_close_usdt", "actual_close_usdt",
        ]].reset_index(drop=True)

    def input_shape(self) -> tuple[int, ...]:
        self._require_setup()
        if self.model_type is ModelType.XGBOOST:
            return (len(next(iter(self._tabular.values())).feature_names),)
        sample, _ = self.dataset(DatasetSplit.TRAIN)[0]
        return tuple(sample.shape)


def load_model_data(
    snapshot: DatasetSnapshot,
    model_type: ModelType | str,
    batch_size: int = 128,
    seed: int = 42,
    *,
    num_workers: int = 0,
    pin_memory: bool = False,
    scale_targets: bool = True,
    target_scaler: TargetScaler | None = None,
) -> ForecastDataModule:
    module = ForecastDataModule(
        snapshot, model_type, batch_size, seed, num_workers, pin_memory,
        scale_targets=scale_targets, target_scaler=target_scaler,
    )
    module.setup()
    return module
