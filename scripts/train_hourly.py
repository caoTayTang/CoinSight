"""Train a single fixed BTC hourly XGBoost candidate and export its backtest."""
import argparse
from pathlib import Path

from pipeline.decision.hourly_model import run_training
from pipeline.settings import DATABASE_URL


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, help='Replay a previously frozen hourly snapshot CSV')
    parser.add_argument('--database-url', default=DATABASE_URL)
    parser.add_argument('--output-root', type=Path, default=Path('data/models/hourly'))
    parser.add_argument('--report', type=Path, default=Path('frontend/public/reports/hourly-backtest.html'))
    args = parser.parse_args()
    run_training(args.snapshot, args.database_url, args.output_root, args.report)


if __name__ == '__main__':
    main()
