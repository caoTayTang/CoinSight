"""Initialize, run, inspect or finally score a frozen prospective hourly study."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from pipeline.decision import hourly_future as future


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'tick', 'status', 'score', 'preflight'])
    parser.add_argument('--source', type=Path)
    parser.add_argument('--study', type=Path)
    parser.add_argument('--output-root', type=Path, default=Path('data/models/hourly-future'))
    args = parser.parse_args()
    if args.action == 'init':
        if args.source is None:
            parser.error('--source is required')
        print(future.initialize(args.source, args.output_root))
        return
    if args.study is None:
        parser.error('--study is required')
    study = args.study.resolve()
    frozen_script = study/'frozen/scripts/hourly_future.py'
    if Path(__file__).resolve() != frozen_script:
        # Always execute the frozen implementation, even when invoked from the repo.
        result = subprocess.run([sys.executable, '-m', 'scripts.hourly_future', args.action,
                                 '--study', str(study)], cwd=study/'frozen')
        raise SystemExit(result.returncode)
    if args.action == 'preflight':
        plan = future.verify(study)
        now = future.clock(plan['api'])
        _, frame = future.klines(plan['api'], (now//future.HOUR-169)*future.HOUR, 169)
        prediction = future.predict_candidate(study/'candidate', frame)
        print(json.dumps(dict(status='ok', context_candles=len(frame), predicted_log_return=prediction,
                              study_forecast=False)))
    else:
        print(json.dumps(getattr(future, args.action)(study), indent=2))


if __name__ == '__main__':
    main()
