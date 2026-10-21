"""Run 28 fixed BTC XGBoost recipes using 2025 validation, never score 2026."""
import argparse
from pathlib import Path

from pipeline.decision.hourly_tuning import run_tuning


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-run', type=Path, required=True, help='Frozen first-run folder with model, snapshot and plan')
    parser.add_argument('--output-root', type=Path, default=Path('data/models/hourly-tuning'))
    parser.add_argument('--html', type=Path, default=Path('frontend/public/reports/hourly-tuning.html'))
    args = parser.parse_args()
    run_tuning(args.base_run, args.output_root, args.html)


if __name__ == '__main__':
    main()
