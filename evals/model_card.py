"""Write the eval results the Desk model picker shows (warehouse_agents/model_card.json).

  python -m evals.model_card evals/reports/train-v3 evals/reports/test-v3

Keyed by model ID, so it matches router routes regardless of their names. The test split is the headline
pass rate; train is kept alongside for reference.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

OUT = Path('warehouse_agents/model_card.json')
FIELDS = ('pass_rate', 'fact_recall', 'latency_p50_ms', 'latency_p95_ms', 'cost_per_1k_queries_usd', 'cases')


def build(train_dir, test_dir):
    models = {}
    for split, directory in (('train', train_dir), ('test', test_dir)):
        summary = json.loads((Path(directory) / 'summary.json').read_text())
        for route, metrics in summary['routes'].items():
            entry = models.setdefault(metrics['model'], {'eval_route': route})
            entry[split] = {k: metrics.get(k) for k in FIELDS}
    for entry in models.values():
        headline = entry.get('test') or entry.get('train') or {}
        entry.update(pass_rate=headline.get('pass_rate'), latency_p50_ms=headline.get('latency_p50_ms'))
    return {
        'source': f'{train_dir} + {test_dir}, docs/evaluation.md',
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'models': models,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('train')
    parser.add_argument('test')
    args = parser.parse_args()
    card = build(args.train, args.test)
    OUT.write_text(json.dumps(card, indent=2) + '\n')
    for model, entry in card['models'].items():
        print(model, entry['pass_rate'], entry['latency_p50_ms'])


if __name__ == '__main__':
    main()
