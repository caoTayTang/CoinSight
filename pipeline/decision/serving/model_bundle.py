"""Build, verify and load immutable daily forecast serving bundles."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.decision.artifacts.store import file_sha256
from pipeline.decision.config import recurrent_config_from_artifact
from pipeline.decision.data.feature_extractor import fused_symbols_from_feature_names
from pipeline.decision.data.scaler import SequenceScaler, TargetScaler
from pipeline.decision.models.factory import build_model
from pipeline.decision.types import ModelType

BUNDLE_FILES = (
    "model.pt",
    "model_config.json",
    "scaler.json",
    "target_scaler.json",
    "feature_names.json",
    "offline_metrics.json",
    "serving_manifest.json",
)


@dataclass
class ForecastModelBundle:
    directory: Path
    manifest: dict[str, Any]
    scaler: SequenceScaler
    target_scaler: TargetScaler
    model: Any

    @classmethod
    def load(
        cls,
        symbol: str,
        version: str | None = None,
        *,
        root: Path | str | None = None,
        device: str = "cpu",
    ) -> "ForecastModelBundle":
        symbol = str(symbol).upper()
        if symbol not in {"BTC", "ETH"}:
            raise ValueError("daily serving supports BTC and ETH only")
        root = Path(root or os.getenv(
            "DAILY_FORECAST_BUNDLE_ROOT", "data/models/daily-forecast"
        ))
        symbol_root = root / symbol
        if version is None:
            active = symbol_root / "active.json"
            if not active.exists():
                raise FileNotFoundError(f"no pinned model bundle for {symbol}")
            version = str(json.loads(active.read_text(encoding="utf-8"))["version"])
        directory = symbol_root / version
        manifest_path = directory / "serving_manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"serving bundle does not exist: {directory}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("symbol") != symbol or manifest.get("model_version") != version:
            raise ValueError("serving manifest identity mismatch")
        if manifest.get("frequency") != "1d" or manifest.get("horizon_periods") != 1:
            raise ValueError("only one-day-ahead daily bundles can be served")
        cls._verify_directory(directory)
        bundle = cls._load_directory(directory, manifest, device)
        return bundle

    @staticmethod
    def _verify_directory(directory: Path) -> None:
        """Verify every byte before deserializing the PyTorch checkpoint."""
        checksums_path = directory / "artifact_checksums.json"
        if not checksums_path.exists():
            raise ValueError("bundle has no artifact checksum manifest")
        checksums = json.loads(checksums_path.read_text(encoding="utf-8"))
        expected_files = set(BUNDLE_FILES)
        if set(checksums) != expected_files:
            raise ValueError("bundle checksum file set is incomplete or unexpected")
        for name, expected in checksums.items():
            path = directory / name
            if not path.is_file() or file_sha256(path) != expected:
                raise ValueError(f"serving artifact checksum mismatch: {name}")

    @classmethod
    def _load_directory(
        cls, directory: Path, manifest: dict[str, Any], device: str
    ) -> "ForecastModelBundle":
        model_type = ModelType.parse(manifest["model_type"])
        if model_type not in {ModelType.GRU, ModelType.LSTM}:
            raise ValueError("daily serving currently requires GRU or LSTM")
        scaler = SequenceScaler.load(directory / "scaler.json")
        target_scaler = TargetScaler.load(directory / "target_scaler.json")
        configured_names = tuple(manifest["feature_names"])
        artifact_names = tuple(json.loads(
            (directory / "feature_names.json").read_text(encoding="utf-8")
        )["feature_names"])
        if scaler.feature_names != configured_names or artifact_names != configured_names:
            raise ValueError("bundle feature order does not match scaler/artifact")
        config = recurrent_config_from_artifact(json.loads(
            (directory / "model_config.json").read_text(encoding="utf-8")
        ))
        if config.input_size != len(configured_names):
            raise ValueError("model input size does not match bundle feature count")
        import torch

        model = build_model(model_type, config)
        checkpoint = torch.load(
            directory / "model.pt", map_location=device, weights_only=True
        )
        model.load_state_dict(checkpoint["state_dict"])
        model.to(device)
        model.eval()
        return cls(directory, manifest, scaler, target_scaler, model)

    @property
    def symbol(self) -> str:
        return str(self.manifest["symbol"])

    @property
    def model_type(self) -> ModelType:
        return ModelType.parse(self.manifest["model_type"])

    @property
    def lookback_periods(self) -> int:
        return int(self.manifest["lookback_periods"])

    @property
    def feature_version(self) -> str:
        return str(self.manifest["feature_version"])

    def required_symbols(self) -> tuple[str, ...]:
        symbols = tuple(self.manifest["asset_order"])
        recovered = fused_symbols_from_feature_names(
            self.scaler.feature_names, self.feature_version
        )
        if symbols != recovered or not symbols or symbols[0] != self.symbol:
            raise ValueError("bundle asset order is invalid")
        return symbols

    def verify_checksums(self) -> None:
        self._verify_directory(self.directory)

    def build_predictor(self, device: str = "cpu"):
        from pipeline.decision.inference.predictor import ForecastPredictor

        return ForecastPredictor(
            self.model,
            self.model_type,
            self.manifest["run_id"],
            scaler=self.scaler,
            target_scaler=self.target_scaler,
            device=device,
            lookback=self.lookback_periods,
            context_symbols=self.required_symbols()[1:],
            feature_version=self.feature_version,
            frequency="1d",
        )


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()
    except Exception:
        return "unknown"


def build_serving_bundle(
    run_directory: Path | str,
    root: Path | str,
    *,
    version: str,
    deployment_tier: str = "research_support",
    activate: bool = False,
) -> Path:
    """Copy a finalized tested run into a checksum-pinned serving directory."""
    run_directory = Path(run_directory)
    root = Path(root)
    run_manifest = json.loads((run_directory / "manifest.json").read_text(encoding="utf-8"))
    run_metadata = json.loads((run_directory / "run.json").read_text(encoding="utf-8"))
    if run_manifest.get("status") != "tested":
        raise ValueError("only a test-consumed run can be pinned for serving")
    symbol = str(run_manifest["symbol"]).upper()
    feature_names = tuple(json.loads(
        (run_directory / "feature_names.json").read_text(encoding="utf-8")
    )["feature_names"])
    feature_version = str(run_manifest["feature_version"])
    asset_order = fused_symbols_from_feature_names(feature_names, feature_version)
    destination = root / symbol / version
    destination.mkdir(parents=True, exist_ok=False)
    for name in (
        "model.pt", "model_config.json", "scaler.json",
        "target_scaler.json", "feature_names.json",
    ):
        shutil.copy2(run_directory / name, destination / name)
    offline = {
        "validation": json.loads(
            (run_directory / "validation_metrics.json").read_text(encoding="utf-8")
        ),
        "test": json.loads(
            (run_directory / "test_metrics.json").read_text(encoding="utf-8")
        ),
    }
    (destination / "offline_metrics.json").write_text(
        json.dumps(offline, indent=2), encoding="utf-8"
    )
    manifest = {
        "model_id": f"{symbol.lower()}-daily-close-{run_manifest['model_type']}",
        "model_version": version,
        "run_id": run_manifest["run_id"],
        "symbol": symbol,
        "model_type": run_manifest["model_type"],
        "frequency": run_manifest["frequency"],
        "feature_version": feature_version,
        "lookback_periods": int(run_manifest["lookback_periods"]),
        "horizon_periods": int(run_manifest["horizon_periods"]),
        "asset_order": list(asset_order),
        "feature_names": list(feature_names),
        "snapshot_id": run_manifest["snapshot_id"],
        "git_commit": run_manifest.get("git_commit", _git_commit()),
        "seed": int(run_manifest["seed"]),
        "source_code": "binance",
        "deployment_tier": deployment_tier,
        "validation_decision": run_manifest.get("validation_decision"),
        "run_finished_at": run_manifest.get("finished_at"),
        "created_from_status": run_metadata.get("status"),
    }
    (destination / "serving_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    checksums = {
        name: file_sha256(destination / name) for name in BUNDLE_FILES
    }
    (destination / "artifact_checksums.json").write_text(
        json.dumps(checksums, indent=2), encoding="utf-8"
    )
    ForecastModelBundle.load(symbol, version, root=root)
    if activate:
        active = root / symbol / "active.json"
        pending = active.with_suffix(".json.pending")
        pending.write_text(json.dumps({"version": version}, indent=2), encoding="utf-8")
        pending.replace(active)
    return destination
