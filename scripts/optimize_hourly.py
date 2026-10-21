"""Run bounded Optuna validation tuning and controlled BTC diagnostics."""
import argparse
from pathlib import Path

from pipeline.decision.hourly_optuna import run_optuna


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-tuning',type=Path,required=True)
    parser.add_argument('--trials',type=int,default=50)
    parser.add_argument('--output-root',type=Path,default=Path('data/models/hourly-optuna'))
    parser.add_argument('--html',type=Path,default=Path('frontend/public/reports/hourly-optuna.html'))
    args=parser.parse_args()
    run_optuna(args.base_tuning,args.trials,args.output_root,args.html)


if __name__=='__main__':
    main()
