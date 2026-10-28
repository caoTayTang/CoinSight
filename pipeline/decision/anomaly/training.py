"""Temporal training and honest diagnostics for market anomaly bundles."""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from pipeline.decision.anomaly.bundle import (
    MarketAnomalyBundle,
    activate_bundle,
    write_checksums,
)
from pipeline.decision.anomaly.features import (
    extract_anomaly_features,
    feature_names,
    required_candles,
)
from pipeline.decision.types import utc_datetime


@dataclass(frozen=True)
class AnomalyTrainingConfig:
    n_estimators: int = 384
    max_samples: int = 512
    max_features: float = 1.0
    threshold_quantile: float = 0.99
    random_state: int = 42
    n_jobs: int = 2

    def __post_init__(self) -> None:
        if self.n_estimators < 32:
            raise ValueError("n_estimators must be at least 32")
        if self.max_samples < 32:
            raise ValueError("max_samples must be at least 32")
        if not 0.95 <= self.threshold_quantile < 1:
            raise ValueError("threshold_quantile must be in [0.95, 1)")


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()
    except Exception:
        return "unknown"


def _digest_frame(frame: pd.DataFrame) -> str:
    canonical = frame.copy()
    canonical["open_time"] = pd.to_datetime(canonical["open_time"], utc=True).map(
        lambda value: value.isoformat()
    )
    encoded = canonical.to_csv(index=False, lineterminator="\n").encode()
    return hashlib.sha256(encoded).hexdigest()


def _profile(frame: pd.DataFrame) -> dict[str, dict[str, float]]:
    result = {}
    for name in frame.columns:
        q1, median, q3 = np.quantile(frame[name].to_numpy(), [0.25, 0.5, 0.75])
        result[name] = {
            "median": float(median),
            "iqr": float(max(q3 - q1, 1e-6)),
        }
    return result


def _distribution(values: np.ndarray) -> dict[str, float]:
    q = np.quantile(values, [0, 0.5, 0.9, 0.95, 0.99, 1])
    return {
        "minimum": float(q[0]),
        "p50": float(q[1]),
        "p90": float(q[2]),
        "p95": float(q[3]),
        "p99": float(q[4]),
        "maximum": float(q[5]),
        "mean": float(np.mean(values)),
    }


def _episode_count(flags: np.ndarray) -> tuple[int, int]:
    lengths: list[int] = []
    current = 0
    for flagged in flags:
        if flagged:
            current += 1
        elif current:
            lengths.append(current)
            current = 0
    if current:
        lengths.append(current)
    return len(lengths), max(lengths, default=0)


def _baseline_flags(features: pd.DataFrame) -> np.ndarray:
    # Transparent comparator, not ground truth: robust/z-like features beyond
    # six scales, extreme range/volatility ratios, or a 35% daily drawdown.
    z_columns = [name for name in features if "_z" in name]
    flags = features[z_columns].abs().max(axis=1).ge(6.0)
    ratio_columns = [name for name in features if "ratio" in name]
    if ratio_columns:
        flags |= features[ratio_columns].max(axis=1).ge(4.0)
    if "drawdown_30d" in features:
        flags |= features["drawdown_30d"].le(-0.35)
    return flags.to_numpy(dtype=bool)


def _agreement(model_flags: np.ndarray, baseline_flags: np.ndarray) -> dict[str, Any]:
    both = int(np.sum(model_flags & baseline_flags))
    either = int(np.sum(model_flags | baseline_flags))
    return {
        "model_alerts": int(model_flags.sum()),
        "robust_baseline_alerts": int(baseline_flags.sum()),
        "both_alert": both,
        "jaccard": None if either == 0 else both / either,
        "agreement_rate": float(np.mean(model_flags == baseline_flags)),
        "note": "Agreement with an unlabeled heuristic is not accuracy.",
    }


def _risk_usefulness(
    candles: pd.DataFrame,
    index: pd.DatetimeIndex,
    flags: np.ndarray,
    frequency: str,
) -> dict[str, Any]:
    raw = candles.copy()
    raw["open_time"] = pd.to_datetime(raw["open_time"], utc=True)
    raw = raw.sort_values("open_time").set_index("open_time")
    close = pd.to_numeric(raw["close_price"], errors="coerce")
    returns = np.log(close / close.shift(1))
    forward = returns.shift(-1).reindex(index)
    horizon = 6 if frequency == "1h" else 7
    future_matrix = pd.concat(
        [returns.shift(-step).reindex(index) for step in range(1, horizon + 1)], axis=1
    )
    realized = future_matrix.std(axis=1, ddof=0)
    valid = forward.notna() & realized.notna()
    flagged = pd.Series(flags, index=index) & valid
    normal = (~pd.Series(flags, index=index)) & valid

    def mean_or_none(values: pd.Series) -> float | None:
        return None if values.empty else float(values.mean())

    flagged_abs = forward[flagged].abs()
    normal_abs = forward[normal].abs()
    flagged_vol = realized[flagged]
    normal_vol = realized[normal]
    return {
        "future_periods": horizon,
        "flagged_samples_with_future": int(flagged.sum()),
        "normal_samples_with_future": int(normal.sum()),
        "mean_next_abs_return_flagged": mean_or_none(flagged_abs),
        "mean_next_abs_return_normal": mean_or_none(normal_abs),
        "next_abs_return_lift": (
            None if flagged_abs.empty or normal_abs.empty or normal_abs.mean() == 0
            else float(flagged_abs.mean() / normal_abs.mean())
        ),
        "mean_future_realized_volatility_flagged": mean_or_none(flagged_vol),
        "mean_future_realized_volatility_normal": mean_or_none(normal_vol),
        "future_volatility_lift": (
            None if flagged_vol.empty or normal_vol.empty or normal_vol.mean() == 0
            else float(flagged_vol.mean() / normal_vol.mean())
        ),
        "interpretation": (
            "A lift above 1 suggests alerts identify higher subsequent market risk. "
            "It does not establish a tradable direction or causal effect."
        ),
    }


def _split_report(
    name: str,
    model: IsolationForest,
    frame: pd.DataFrame,
    threshold: float,
    candles: pd.DataFrame,
    frequency: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    scores = -model.score_samples(frame)
    flags = scores >= threshold
    baseline = _baseline_flags(frame)
    episodes, longest = _episode_count(flags)
    scored = pd.DataFrame(
        {
            "cutoff_time": frame.index
            + (pd.Timedelta(hours=1) if frequency == "1h" else pd.Timedelta(days=1)),
            "score": scores,
            "is_anomaly": flags,
            "robust_baseline_flag": baseline,
        },
        index=frame.index,
    )
    monthly = []
    for period, group in scored.groupby(scored["cutoff_time"].dt.strftime("%Y-%m")):
        monthly.append({
            "month": period,
            "samples": len(group),
            "alerts": int(group["is_anomaly"].sum()),
            "alert_rate": float(group["is_anomaly"].mean()),
        })
    top = scored.nlargest(min(10, len(scored)), "score")
    report = {
        "split": name,
        "sample_count": len(frame),
        "score_distribution": _distribution(scores),
        "alerts": int(flags.sum()),
        "alert_rate": float(flags.mean()),
        "alert_episodes": episodes,
        "longest_alert_episode_periods": longest,
        "robust_baseline_comparison": _agreement(flags, baseline),
        "future_risk_usefulness": _risk_usefulness(
            candles, frame.index, flags, frequency
        ),
        "monthly": monthly,
        "top_alerts": [
            {
                "candle_open": index.isoformat(),
                "cutoff": row["cutoff_time"].isoformat(),
                "score": float(row["score"]),
            }
            for index, row in top.iterrows()
        ],
    }
    return report, scored


def train_bundle(
    candles: pd.DataFrame,
    *,
    symbol: str,
    frequency: str,
    train_start: str | datetime,
    calibration_start: str | datetime,
    test_start: str | datetime,
    end: str | datetime,
    version: str,
    root: Path | str,
    config: AnomalyTrainingConfig | None = None,
    activate: bool = False,
) -> Path:
    """Fit once, calibrate once, and report on a later untouched period."""
    symbol = str(symbol).upper()
    if symbol not in {"BTC", "ETH"}:
        raise ValueError("symbol must be BTC or ETH")
    if frequency not in {"1h", "1d"}:
        raise ValueError("frequency must be 1h or 1d")
    config = config or AnomalyTrainingConfig()
    train_start, calibration_start, test_start, end = map(
        utc_datetime, (train_start, calibration_start, test_start, end)
    )
    if not train_start < calibration_start < test_start < end:
        raise ValueError("require train_start < calibration_start < test_start < end")
    step = pd.Timedelta(hours=1) if frequency == "1h" else pd.Timedelta(days=1)
    ordered_times = pd.DatetimeIndex(
        pd.to_datetime(candles["open_time"], utc=True).sort_values()
    )
    if ordered_times.duplicated().any() or not ordered_times.to_series().diff().dropna().eq(step).all():
        raise ValueError(f"{symbol}/{frequency} training snapshot has gaps or duplicate candles")
    extracted = extract_anomaly_features(candles, frequency)
    post_warmup = extracted.iloc[required_candles(frequency) - 1 :]
    if post_warmup.empty or post_warmup.isna().any().any():
        raise ValueError(f"{symbol}/{frequency} training snapshot has invalid candles/features")
    features = extracted.dropna()
    cutoff = features.index + step
    partitions = {
        "train": features[(cutoff >= train_start) & (cutoff < calibration_start)],
        "calibration": features[(cutoff >= calibration_start) & (cutoff < test_start)],
        "test": features[(cutoff >= test_start) & (cutoff < end)],
    }
    minimums = {"train": 200, "calibration": 50, "test": 20}
    for name, frame in partitions.items():
        if len(frame) < minimums[name]:
            raise ValueError(
                f"{symbol}/{frequency} {name} has {len(frame)} usable rows; "
                f"requires at least {minimums[name]}"
            )
        if not np.isfinite(frame.to_numpy()).all():
            raise ValueError(f"{name} contains non-finite anomaly features")
    model = IsolationForest(
        n_estimators=config.n_estimators,
        max_samples=min(config.max_samples, len(partitions["train"])),
        max_features=config.max_features,
        contamination="auto",
        random_state=config.random_state,
        n_jobs=config.n_jobs,
    ).fit(partitions["train"])
    calibration_scores = -model.score_samples(partitions["calibration"])
    threshold = float(np.quantile(calibration_scores, config.threshold_quantile))
    root = Path(root)
    directory = root / symbol / frequency / version
    directory.mkdir(parents=True, exist_ok=False)
    joblib.dump(model, directory / "model.joblib")
    snapshot = candles.copy()
    snapshot["open_time"] = pd.to_datetime(snapshot["open_time"], utc=True)
    snapshot = snapshot.sort_values("open_time")
    snapshot.to_csv(directory / "training_snapshot.csv.gz", index=False, compression="gzip")
    snapshot_sha256 = _digest_frame(snapshot)
    feature_config = {
        "feature_version": f"market-anomaly-{frequency}-v2",
        "feature_names": list(feature_names(frequency)),
        "required_candles": required_candles(frequency),
        "causality": "All reference windows exclude the candle being scored via shift(1).",
        "reference_profile": _profile(partitions["train"]),
    }
    (directory / "feature_config.json").write_text(
        json.dumps(feature_config, indent=2, allow_nan=False), encoding="utf-8"
    )
    plan = {
        "symbol": symbol,
        "frequency": frequency,
        "train_start": train_start.isoformat(),
        "train_end_exclusive": calibration_start.isoformat(),
        "calibration_start": calibration_start.isoformat(),
        "calibration_end_exclusive": test_start.isoformat(),
        "test_start": test_start.isoformat(),
        "test_end_exclusive": end.isoformat(),
        "split_by": "closed-candle cutoff time",
        "labels_used": False,
        "hyperparameter_search_on_test": False,
        "threshold_policy": "calibration score quantile; higher score is more unusual",
        "training_config": config.__dict__,
        "source_snapshot_sha256": snapshot_sha256,
        "source_rows": len(snapshot),
        "created_at": datetime.now(UTC).isoformat(),
    }
    (directory / "training_plan.json").write_text(
        json.dumps(plan, indent=2, allow_nan=False), encoding="utf-8"
    )
    split_reports = {}
    score_files = {}
    for name, frame in partitions.items():
        report, scores = _split_report(
            name, model, frame, threshold, snapshot, frequency
        )
        split_reports[name] = report
        path = directory / f"{name}_scores.csv"
        scores.to_csv(path, index_label="candle_open")
        score_files[name] = path.name
    evaluation = {
        "claim": "No precision/recall/accuracy is claimed because no anomaly labels exist.",
        "threshold": threshold,
        "threshold_quantile": config.threshold_quantile,
        "splits": split_reports,
        "score_files": score_files,
        "manual_review_required": [
            "Inspect top alerts against known market events and data-quality incidents.",
            "Prefer prospective alert logging before using this signal operationally.",
        ],
    }
    (directory / "evaluation.json").write_text(
        json.dumps(evaluation, indent=2, allow_nan=False), encoding="utf-8"
    )
    manifest = {
        "model_id": f"{symbol.lower()}-{frequency}-market-anomaly",
        "model_version": version,
        "symbol": symbol,
        "frequency": frequency,
        "algorithm": "IsolationForest",
        "feature_version": feature_config["feature_version"],
        "feature_names": feature_config["feature_names"],
        "required_candles": feature_config["required_candles"],
        "threshold": threshold,
        "threshold_quantile": config.threshold_quantile,
        "seed": config.random_state,
        "source_code": "binance",
        "git_commit": _git_commit(),
        "deployment_tier": "research_support",
        "limitations": (
            "Unsupervised unusualness only; not event classification, probability, "
            "direction, or a trading decision."
        ),
    }
    (directory / "serving_manifest.json").write_text(
        json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8"
    )
    write_checksums(directory)
    MarketAnomalyBundle.load(symbol, frequency, version, root=root)
    if activate:
        activate_bundle(root, symbol, frequency, version)
    return directory
