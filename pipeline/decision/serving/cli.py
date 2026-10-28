"""Prepare pinned bundles and run the daily forecast support service."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pipeline.decision.serving.model_bundle import build_serving_bundle
from pipeline.decision.serving.support_service import forecast_support


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    bundle = commands.add_parser("build-bundle")
    bundle.add_argument("--run-directory", required=True)
    bundle.add_argument("--root", default="data/models/daily-forecast")
    bundle.add_argument("--version", required=True)
    bundle.add_argument("--activate", action="store_true")
    report = commands.add_parser("report")
    report.add_argument("--symbol", choices=("BTC", "ETH"), default="BTC")
    report.add_argument("--performance-days", type=int, default=30)
    report.add_argument("--market-days", type=int, default=30)
    report.add_argument("--trend-hours", type=int, default=168)
    report.add_argument("--cutoff")
    args = parser.parse_args()
    if args.command == "build-bundle":
        path = build_serving_bundle(
            args.run_directory,
            args.root,
            version=args.version,
            activate=args.activate,
        )
        print(json.dumps({"bundle": str(path)}, indent=2))
    else:
        print(json.dumps(forecast_support(
            symbol=args.symbol,
            performance_days=args.performance_days,
            market_days=args.market_days,
            trend_hours=args.trend_hours,
            cutoff=args.cutoff,
        ), indent=2))


if __name__ == "__main__":
    main()
