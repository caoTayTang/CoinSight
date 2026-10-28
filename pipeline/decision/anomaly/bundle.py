"""Checksum-pinned serving bundles for per-asset Isolation Forest models."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from pipeline.decision.anomaly.features import (
    extract_anomaly_features,
    feature_names,
    required_candles,
)
from pipeline.decision.artifacts.store import file_sha256

PUBLIC_SYMBOLS = ("BTC", "ETH")
BUNDLE_FILES = (
    "model.joblib",
    "feature_config.json",
    "training_plan.json",
    "evaluation.json",
    "serving_manifest.json",
)


@dataclass
class MarketAnomalyBundle:
    directory: Path
    manifest: dict[str, Any]
    feature_config: dict[str, Any]
    model: Any

    @classmethod
    def load(
        cls,
        symbol: str,
        frequency: str,
        version: str | None = None,
        *,
        root: Path | str | None = None,
    ) -> "MarketAnomalyBundle":
        symbol = str(symbol).upper()
        if symbol not in PUBLIC_SYMBOLS:
            raise ValueError(f"symbol must be one of {list(PUBLIC_SYMBOLS)}")
        if frequency not in {"1h", "1d"}:
            raise ValueError("frequency must be 1h or 1d")
        root = Path(root or os.getenv(
            "MARKET_ANOMALY_BUNDLE_ROOT", "data/models/market-anomaly"
        ))
        frequency_root = root / symbol / frequency
        if version is None:
            active_path = frequency_root / "active.json"
            if not active_path.is_file():
                raise FileNotFoundError(f"no active anomaly bundle for {symbol}/{frequency}")
            version = str(json.loads(active_path.read_text(encoding="utf-8"))["version"])
        directory = frequency_root / version
        cls._verify(directory)
        manifest = json.loads((directory / "serving_manifest.json").read_text(encoding="utf-8"))
        feature_config = json.loads((directory / "feature_config.json").read_text(encoding="utf-8"))
        if (
            manifest.get("symbol") != symbol
            or manifest.get("frequency") != frequency
            or manifest.get("model_version") != version
        ):
            raise ValueError("anomaly serving manifest identity mismatch")
        expected = list(feature_names(frequency))
        if feature_config.get("feature_names") != expected:
            raise ValueError("anomaly feature order does not match the code contract")
        if int(feature_config.get("required_candles", 0)) != required_candles(frequency):
            raise ValueError("anomaly history requirement does not match the code contract")
        model = joblib.load(directory / "model.joblib")
        if int(getattr(model, "n_features_in_", -1)) != len(expected):
            raise ValueError("anomaly model input width mismatch")
        return cls(directory, manifest, feature_config, model)

    @staticmethod
    def _verify(directory: Path) -> None:
        checksums_path = directory / "artifact_checksums.json"
        if not checksums_path.is_file():
            raise FileNotFoundError(f"missing anomaly bundle checksum manifest: {directory}")
        checksums = json.loads(checksums_path.read_text(encoding="utf-8"))
        if set(checksums) != set(BUNDLE_FILES):
            raise ValueError("anomaly checksum file set is incomplete or unexpected")
        for name, expected in checksums.items():
            path = directory / name
            if not path.is_file() or file_sha256(path) != expected:
                raise ValueError(f"anomaly artifact checksum mismatch: {name}")

    @property
    def threshold(self) -> float:
        return float(self.manifest["threshold"])

    @property
    def required_candles(self) -> int:
        return int(self.feature_config["required_candles"])

    @property
    def frequency(self) -> str:
        return str(self.manifest["frequency"])

    def score(self, candles: pd.DataFrame) -> dict[str, Any]:
        features = extract_anomaly_features(candles, self.frequency)
        latest = features.iloc[[-1]]
        if latest.isna().any().any():
            raise ValueError(
                f"need {self.required_candles} contiguous valid {self.frequency} candles"
            )
        score = float(-self.model.score_samples(latest)[0])
        profile = self.feature_config["reference_profile"]
        deviations = []
        for name in feature_names(self.frequency):
            value = float(latest.iloc[0][name])
            reference = profile[name]
            scaled = (value - float(reference["median"])) / max(
                float(reference["iqr"]), 1e-6
            )
            deviations.append({
                "feature": name,
                "value": value,
                "train_median": float(reference["median"]),
                "iqr_scaled_deviation": float(scaled),
            })
        opened = pd.Timestamp(latest.index[-1])
        step = pd.Timedelta(hours=1) if self.frequency == "1h" else pd.Timedelta(days=1)
        return {
            "method": "isolation_forest_causal_v2",
            "symbol": self.manifest["symbol"],
            "frequency": self.frequency,
            "model_version": self.manifest["model_version"],
            "model_sha256": file_sha256(self.directory / "model.joblib"),
            "inspected_candle_open": opened.isoformat(),
            "cutoff": (opened + step).isoformat(),
            "score": score,
            "threshold": self.threshold,
            "is_anomaly": bool(score >= self.threshold),
            "threshold_quantile": float(self.manifest["threshold_quantile"]),
            "largest_feature_deviations": sorted(
                deviations,
                key=lambda item: abs(item["iqr_scaled_deviation"]),
                reverse=True,
            )[:5],
            "interpretation": (
                "Unsupervised unusualness versus the training regime; the score and "
                "threshold are not a crash probability or a trading instruction."
            ),
        }


def activate_bundle(root: Path | str, symbol: str, frequency: str, version: str) -> Path:
    root = Path(root)
    # Loading first prevents an invalid bundle from becoming active.
    MarketAnomalyBundle.load(symbol, frequency, version, root=root)
    active = root / symbol.upper() / frequency / "active.json"
    pending = active.with_suffix(".json.pending")
    pending.write_text(json.dumps({"version": version}, indent=2), encoding="utf-8")
    pending.replace(active)
    return active


def write_checksums(directory: Path) -> None:
    checksums = {name: file_sha256(directory / name) for name in BUNDLE_FILES}
    (directory / "artifact_checksums.json").write_text(
        json.dumps(checksums, indent=2), encoding="utf-8"
    )
