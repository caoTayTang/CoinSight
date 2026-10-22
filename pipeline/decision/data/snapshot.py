"""Create immutable, checksummed Parquet snapshots from warehouse candles."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd

from pipeline.decision.config import ForecastDataConfig
from pipeline.decision.data.coverage import CoverageAuditor
from pipeline.decision.data.feature_extractor import (
    MultiAssetFeatureFusion,
    feature_extractor,
    fused_sequence_feature_names,
    is_fused_feature_version,
)
from pipeline.decision.data.sample_index import SampleIndexBuilder
from pipeline.decision.data.split import TimeSeriesSplitter
from pipeline.decision.types import DatasetSnapshot, utc_datetime


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_state() -> dict[str, str | bool | None]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()
        dirty = bool(subprocess.run(
            ["git", "status", "--porcelain"], check=True, capture_output=True, text=True
        ).stdout.strip())
        return {"commit": commit, "dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}


class SnapshotBuilder:
    def __init__(
        self,
        repository,
        config: ForecastDataConfig,
        root: Path,
    ):
        self.repository = repository
        self.config = config
        self.root = Path(root)

    def build(self, symbol: str, start: datetime, cutoff: datetime) -> DatasetSnapshot:
        symbol = symbol.upper()
        start, cutoff = utc_datetime(start), utc_datetime(cutoff)
        candles = self.repository.fetch_candles(symbol, start, cutoff)
        report = CoverageAuditor(self.config.frequency).audit(
            candles, start, cutoff, symbol
        )
        if report.row_count == 0:
            raise ValueError(f"{symbol}: no candles available for a snapshot")
        if report.duplicate_count:
            raise ValueError(f"{symbol}: duplicate candles must be fixed before snapshotting")
        extractor = feature_extractor(self.config.feature_version)
        features = extractor.transform(candles)
        context_candles = pd.DataFrame()
        context_symbols: tuple[str, ...] = ()
        sequence_names = extractor.feature_names()
        if is_fused_feature_version(self.config.feature_version):
            context_symbols = tuple(sorted(
                set(self.config.context_symbols) - {symbol}
            ))
            if context_symbols:
                fetch_many = getattr(self.repository, "fetch_candles_many", None)
                if callable(fetch_many):
                    context_candles = fetch_many(context_symbols, start, cutoff)
                else:
                    frames = [
                        self.repository.fetch_candles(item, start, cutoff)
                        for item in context_symbols
                    ]
                    frames = [frame for frame in frames if not frame.empty]
                    if frames:
                        context_candles = pd.concat(frames, ignore_index=True)
            features = MultiAssetFeatureFusion().attach(
                features,
                context_candles,
                symbol,
                context_symbols,
                self.config.feature_version,
            )
            sequence_names = fused_sequence_feature_names(
                symbol, context_symbols, self.config.feature_version
            )
        samples = SampleIndexBuilder().build(
            candles,
            features,
            self.config.lookback_periods,
            self.config.horizon_periods,
            self.config.frequency,
        )
        samples = TimeSeriesSplitter().assign(samples, self.config.boundaries(cutoff))
        if samples.empty:
            raise ValueError("snapshot contains no forecasting samples")

        identity = hashlib.sha256()
        identity.update(symbol.encode())
        identity.update(cutoff.isoformat().encode())
        identity.update(json.dumps({
            "feature_version": self.config.feature_version,
            "frequency": self.config.frequency,
            "lookback_periods": self.config.lookback_periods,
            "horizon_periods": self.config.horizon_periods,
            "rolling_baseline_periods": self.config.rolling_baseline_periods,
            "minimum_month_samples": self.config.minimum_month_samples,
            "validation_start": self.config.validation_start.isoformat(),
            "test_start": self.config.test_start.isoformat(),
            "context_symbols": context_symbols,
            "sequence_feature_names": sequence_names,
        }, sort_keys=True).encode())
        identity.update(pd.util.hash_pandas_object(candles, index=False).values.tobytes())
        if not context_candles.empty:
            hashed_context = context_candles.sort_values(
                ["symbol", "open_time"]
            ).reset_index(drop=True)
            identity.update(
                pd.util.hash_pandas_object(hashed_context, index=False).values.tobytes()
            )
        snapshot_id = f"{cutoff:%Y%m%dT%H%M%SZ}-{identity.hexdigest()[:12]}"
        destination = self.root / snapshot_id / symbol
        if destination.exists():
            snapshot = self.load(snapshot_id, symbol)
            self.verify_hashes(snapshot)
            return snapshot

        temporary = destination.with_name(f".{destination.name}-{uuid4().hex}.tmp")
        temporary.mkdir(parents=True, exist_ok=False)
        try:
            files = {
                "candles.parquet": candles,
                "features.parquet": features,
                "samples.parquet": samples,
            }
            for name, frame in files.items():
                try:
                    frame.to_parquet(temporary / name, index=False)
                except ImportError as error:
                    raise RuntimeError("pyarrow is required to write forecasting snapshots") from error
            manifest = {
                "snapshot_id": snapshot_id,
                "symbol": symbol,
                "source_code": self.config.source_code,
                "feature_version": self.config.feature_version,
                "frequency": self.config.frequency,
                "lookback_periods": self.config.lookback_periods,
                "horizon_periods": self.config.horizon_periods,
                "rolling_baseline_periods": self.config.rolling_baseline_periods,
                "minimum_month_samples": self.config.minimum_month_samples,
                # Legacy keys keep older consumers readable for hourly runs.
                "lookback_hours": (
                    self.config.lookback_periods
                    if self.config.frequency == "1h" else None
                ),
                "horizon_hours": (
                    self.config.horizon_periods
                    if self.config.frequency == "1h" else None
                ),
                "context_symbols": list(context_symbols),
                "asset_order": [symbol, *context_symbols],
                "sequence_feature_names": list(sequence_names),
                "start": start.isoformat(),
                "cutoff": cutoff.isoformat(),
                "split_boundaries": {
                    "validation_start": self.config.validation_start.isoformat(),
                    "test_start": self.config.test_start.isoformat(),
                    "test_end": cutoff.isoformat(),
                },
                "row_counts": {
                    "candles": len(candles),
                    "features": len(features),
                    "samples": len(samples),
                    "valid_samples": int(samples["is_valid"].sum()),
                    "context_candles": len(context_candles),
                },
                "rejections": {
                    str(key): int(value)
                    for key, value in samples.loc[~samples["is_valid"], "rejection_reason"]
                    .value_counts(dropna=False).items()
                },
                "batch_ids": self.repository.fetch_source_batch_ids(symbol, start, cutoff),
                "context_batch_ids": sorted({
                    int(value) for value in context_candles.get(
                        "batch_id", pd.Series(dtype=int)
                    ).dropna()
                }),
                "context_coverage": {
                    str(key): int(value)
                    for key, value in context_candles.get(
                        "symbol", pd.Series(dtype=str)
                    ).astype(str).str.upper().value_counts().sort_index().items()
                },
                "coverage": report.to_dict(),
                "git": git_state(),
            }
            manifest["files"] = {
                name: sha256_file(temporary / name) for name in files
            }
            (temporary / "manifest.json").write_text(
                json.dumps(manifest, indent=2, default=str), encoding="utf-8"
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary.rename(destination)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return DatasetSnapshot(snapshot_id, symbol, self.root, manifest)

    def load(self, snapshot_id: str, symbol: str) -> DatasetSnapshot:
        directory = self.root / snapshot_id / symbol.upper()
        manifest_path = directory / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"forecast snapshot not found: {directory}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        snapshot = DatasetSnapshot(snapshot_id, symbol.upper(), self.root, manifest)
        self.verify_hashes(snapshot)
        return snapshot

    def verify_hashes(self, snapshot: DatasetSnapshot) -> None:
        for name, expected in snapshot.manifest.get("files", {}).items():
            path = snapshot.directory / name
            if not path.exists() or sha256_file(path) != expected:
                raise ValueError(f"snapshot checksum mismatch: {path}")
