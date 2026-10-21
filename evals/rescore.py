"""Re-score saved results with the current scorer, without calling any model.

Use after a scorer fix: python -m evals.rescore evals/reports/test-v0 [--dsn ...]
Rows saved before facts were stored rebuild them from the fixture database.
--merge DIR replaces rows with re-run rows of the same route and case (e.g. after a provider outage).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from evals import cases as case_set
from evals import fixtures
from evals.report import write_reports
from evals.run import PRICING, context_for
from evals.scoring import aggregate, score_case


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('out')
    parser.add_argument('--dsn', default=os.getenv('EVAL_DATABASE_URL'))
    parser.add_argument('--merge', help='directory of re-run results that replace matching rows')
    args = parser.parse_args()
    out = Path(args.out)
    by_id = {c.id: c for c in case_set.all_cases()}
    pricing = json.loads(PRICING.read_text()) if PRICING.exists() else {}
    # A run that crashed part-way leaves results but no summary; rebuild it from the rows and the routes file.
    summary_path = out / 'summary.json'
    if summary_path.exists():
        summary = json.loads(summary_path.read_text())
    else:
        summary = dict(
            meta=dict(
                split=out.name, backend='live', generated_at='rebuilt from results', rebuilt_from_results=True
            ),
            routes={},
        )
    configured = {r['name']: r for r in json.loads(Path('evals/routes.json').read_text())['routes']}
    facts_cache = {}
    for path in sorted(out.glob('results-*.jsonl')):
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        if args.merge and (Path(args.merge) / path.name).exists():
            rerun = {
                r['case']: r for r in map(json.loads, (Path(args.merge) / path.name).read_text().splitlines())
            }
            rows = [rerun.get(r['case'], r) for r in rows]
        for row in rows:
            if 'facts' not in row:
                if row['scenario'] not in facts_cache:
                    facts_cache[row['scenario']] = fixtures.build(args.dsn, row['scenario'])
                row['facts'] = facts_cache[row['scenario']]
            row['score'] = score_case(by_id[row['case']], row, row['facts'], context_for(row['question']))
        path.write_text(''.join(json.dumps(r, default=str, ensure_ascii=False) + '\n' for r in rows))
        name = path.stem.removeprefix('results-')
        model = summary['routes'].get(name, {}).get('model') or configured.get(name, {}).get('model')
        summary['meta'].setdefault('cases', len(rows))
        summary['meta'].setdefault('generated_at', 'rebuilt from results')
        summary['routes'][name] = dict(model=model, **aggregate(rows, pricing.get(model)))
    write_reports(out, summary['meta'], summary['routes'])
    print(json.dumps({k: v['pass_rate'] for k, v in summary['routes'].items()}))


if __name__ == '__main__':
    main()
