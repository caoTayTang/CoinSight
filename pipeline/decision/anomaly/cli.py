"""CLI for training the four BTC/ETH hourly/daily anomaly bundles."""
from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path

from pipeline.decision.anomaly.bundle import activate_bundle
from pipeline.decision.anomaly.features import required_candles
from pipeline.decision.anomaly.training import AnomalyTrainingConfig, train_bundle
from pipeline.decision.data.warehouse_repository import candle_repository
from pipeline.decision.types import utc_datetime
from pipeline.settings import DATABASE_URL, SETTINGS


def _defaults() -> dict:
    return dict(SETTINGS.get("market_anomaly", {}))


def train(args) -> Path:
    if not args.end:
        raise ValueError("--end is required when training")
    step = timedelta(hours=1) if args.frequency == "1h" else timedelta(days=1)
    start = utc_datetime(args.train_start) - required_candles(args.frequency) * step
    end = utc_datetime(args.end)
    repository = candle_repository(
        args.frequency, database_url=args.database_url, source_code=args.source_code
    )
    candles = repository.fetch_candles(args.symbol, start, end)
    return train_bundle(
        candles,
        symbol=args.symbol,
        frequency=args.frequency,
        train_start=args.train_start,
        calibration_start=args.calibration_start,
        test_start=args.test_start,
        end=args.end,
        version=args.version,
        root=args.root,
        config=AnomalyTrainingConfig(
            n_estimators=args.n_estimators,
            max_samples=args.max_samples,
            threshold_quantile=args.threshold_quantile,
            random_state=args.seed,
            n_jobs=args.workers,
        ),
        activate=args.activate,
    )


def parser() -> argparse.ArgumentParser:
    defaults = _defaults()
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--symbol", required=True, choices=("BTC", "ETH"))
    result.add_argument("--frequency", required=True, choices=("1h", "1d"))
    result.add_argument("--train-start", default=defaults.get("train_start", "2020-01-01T00:00:00Z"))
    result.add_argument("--calibration-start", default=defaults.get("calibration_start", "2025-01-01T00:00:00Z"))
    result.add_argument("--test-start", default=defaults.get("test_start", "2026-01-01T00:00:00Z"))
    result.add_argument("--end", help="Exclusive UTC end; freeze this before reviewing test output.")
    result.add_argument("--version", required=True)
    result.add_argument("--root", type=Path, default=Path("data/models/market-anomaly"))
    result.add_argument("--database-url", default=DATABASE_URL)
    result.add_argument("--source-code", default=defaults.get("source_code", "binance"))
    result.add_argument("--n-estimators", type=int, default=int(defaults.get("n_estimators", 384)))
    result.add_argument("--max-samples", type=int, default=int(defaults.get("max_samples", 512)))
    result.add_argument("--threshold-quantile", type=float, default=float(defaults.get("threshold_quantile", 0.99)))
    result.add_argument("--seed", type=int, default=int(defaults.get("seed", 42)))
    result.add_argument("--workers", type=int, default=int(defaults.get("workers", 2)))
    result.add_argument("--activate", action="store_true")
    result.add_argument(
        "--activate-existing",
        action="store_true",
        help="Verify and activate an existing version without retraining.",
    )
    return result


def main() -> None:
    args = parser().parse_args()
    if args.activate_existing:
        print(activate_bundle(args.root, args.symbol, args.frequency, args.version))
    else:
        print(train(args))


if __name__ == "__main__":
    main()
