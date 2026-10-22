"""Small frozen smoke benchmark. Not an independent production quality estimate."""

import argparse
import hashlib
import json
import time
from pathlib import Path
from warehouse_agents.retrieval import search

CASES = [
    ('container down timeout connection refused', 'service-unreachable'),
    ('service health reachable endpoint HTTP 503', 'service-unreachable'),
    ('PSI feature distribution reference bins', 'model-drift'),
    ('does drift prove current forecast MAE failure', 'model-drift'),
    ('missing closed UTC candles stale data', 'missing-candles'),
    ('warehouse missing hours duplicate grain', 'missing-candles'),
    ('staging rejected duplicate accepted accounting_delta', 'warehouse-reconciliation'),
    ('materialized mart parity volume mismatch', 'warehouse-reconciliation'),
    ('incident summary findings next steps report', 'incident-report'),
    ('zzzzquuxxy', None),
]


def evaluate(mode):
    rows = []
    for question, expected in CASES:
        start = time.perf_counter()
        result = search(question, mode=mode)
        ranks = [i + 1 for i, h in enumerate(result['hits']) if expected and f'/{expected}/' in h['source']]
        rows.append(
            dict(
                question=question,
                expected=expected,
                reciprocal_rank=1 / min(ranks) if ranks else 0,
                hit=bool(ranks) if expected else not result['hits'],
                latency_ms=(time.perf_counter() - start) * 1000,
            )
        )
    positives = [r for r in rows if r['expected']]
    return dict(
        mode=mode,
        benchmark_sha256=hashlib.sha256(json.dumps(CASES).encode()).hexdigest(),
        corpus_sha256=result['corpus_sha256'],
        recall_at_3=sum(r['hit'] for r in positives) / len(positives),
        mrr_at_3=sum(r['reciprocal_rank'] for r in positives) / len(positives),
        cases=rows,
        limitations='Author-created English smoke set, visible during implementation. No independent test, faithfulness, or production accuracy claim.',
    )


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--mode', default='bm25', choices=['bm25', 'dense', 'hybrid', 'hybrid_rerank'])
    p.add_argument('--output', required=True)
    a = p.parse_args()
    report = evaluate(a.mode)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != 'cases'}, indent=2))
