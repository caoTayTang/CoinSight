"""Preregister and run a fixed BTC+ETH experiment; --offline needs no future study."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from pipeline.decision import hourly_cross_asset as cross


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'run', 'status'])
    parser.add_argument('--source', type=Path)
    parser.add_argument('--future-study', type=Path)
    parser.add_argument('--offline', action='store_true', help='Explicit one-shot retrospective mode at initialization')
    parser.add_argument('--experiment', type=Path)
    parser.add_argument('--output-root', type=Path, default=Path('data/models/hourly-cross-asset'))
    args = parser.parse_args()
    if args.action == 'init':
        if args.source is None or (args.future_study is None and not args.offline):
            parser.error('--source and either --offline or --future-study are required')
        print(cross.initialize(args.source, args.future_study, args.output_root, offline=args.offline))
        return
    if args.experiment is None:
        parser.error('--experiment is required')
    experiment = args.experiment.resolve()
    if Path(__file__).resolve() != experiment/'frozen/scripts/hourly_cross_asset.py':
        result = subprocess.run([sys.executable, '-B', '-m', 'scripts.hourly_cross_asset', args.action,
            '--experiment', str(experiment)], cwd=experiment/'frozen')
        raise SystemExit(result.returncode)
    if args.action == 'status':
        plan = cross.verify(experiment)
        result = dict(gate_open=cross.gate_open(plan), completed=(experiment/'report.json').exists(),
                      folds=plan['folds'], extra_columns=plan['extra_columns'])
    else:
        result = cross.execute(experiment)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
