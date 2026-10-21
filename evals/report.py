"""Markdown and JSON reports for an eval run."""

from __future__ import annotations

import json
from pathlib import Path

HEADLINE = (
    ('pass_rate', 'Pass rate', 'pct'),
    ('pass_rate_completed', 'Pass rate (excl. provider errors)', 'pct'),
    ('tool_selection_accuracy', 'Tool selection', 'pct'),
    ('argument_accuracy', 'Arguments', 'pct'),
    ('fact_recall', 'Fact recall', 'pct'),
    ('hallucinated_number_rate', 'Hallucinated numbers', 'pct'),
    ('fabricated_citation_rate', 'Answers with fabricated citations', 'pct'),
    ('abstention_accuracy', 'Abstains when data is unavailable', 'pct'),
    ('refusal_accuracy', 'Refuses writes/advice', 'pct'),
    ('injection_resistance', 'Injection resistance', 'pct'),
    ('credential_rejection', 'Credential rejection', 'pct'),
    ('secret_leaks', 'Secret leaks', 'int'),
    ('error_rate', 'Provider/run errors', 'pct'),
    ('latency_p50_ms', 'Latency p50 (ms)', 'int'),
    ('latency_p95_ms', 'Latency p95 (ms)', 'int'),
    ('mean_llm_calls', 'Model calls / query', 'num'),
    ('mean_input_tokens', 'Input tokens / query', 'int'),
    ('mean_output_tokens', 'Output tokens / query', 'int'),
    ('cost_per_1k_queries_usd', 'Cost / 1k queries (USD)', 'num'),
)


def _fmt(value, kind):
    if value is None:
        return '–'
    if kind == 'pct':
        return f'{value * 100:.1f}%'
    if kind == 'int':
        return f'{int(value):,}'
    return f'{value:g}'


def markdown(meta, summaries):
    names = list(summaries)
    lines = [
        f'# CoinSight agent eval — split `{meta["split"]}`',
        '',
        f'{meta["cases"]} cases per route · backend `{meta["backend"]}` · generated {meta["generated_at"]}',
        '',
        '| Metric | ' + ' | '.join(f'{n}<br>`{summaries[n].get("model") or "replay"}`' for n in names) + ' |',
        '|---|' + '---:|' * len(names),
    ]
    for key, label, kind in HEADLINE:
        lines.append(f'| {label} | ' + ' | '.join(_fmt(summaries[n].get(key), kind) for n in names) + ' |')
    categories = sorted({c for s in summaries.values() for c in s['pass_rate_by_category']})
    lines += [
        '',
        '## Pass rate by category',
        '',
        '| Category | ' + ' | '.join(names) + ' |',
        '|---|' + '---:|' * len(names),
    ]
    for category in categories:
        lines.append(
            f'| {category} | '
            + ' | '.join(_fmt(summaries[n]['pass_rate_by_category'].get(category), 'pct') for n in names)
            + ' |'
        )
    lines += ['', 'Metric definitions and limits: [docs/evaluation.md](../../../docs/evaluation.md).', '']
    return '\n'.join(lines)


def failures(out: Path):
    lines = ['# Failed cases', '']
    for path in sorted(out.glob('results-*.jsonl')):
        for row in map(json.loads, path.read_text().splitlines()):
            s = row['score']
            if s['passed']:
                continue
            reasons = []
            if s.get('error'):
                reasons.append(f'error: {s["error"][:120]}')
            if s.get('tools_ok') is False:
                reasons.append('tools: ' + ', '.join(e['tool'] for e in row['evidence']) or 'none')
            if s.get('args_ok') is False:
                reasons.append('arguments')
            if s['fact_hits'] < s['fact_total']:
                reasons.append(f'facts {s["fact_hits"]}/{s["fact_total"]}')
            if s['numbers_ungrounded']:
                reasons.append('ungrounded: ' + ', '.join(s['numbers_ungrounded'][:5]))
            if not s['behavior_ok'] and not reasons:
                reasons.append(f'behavior ({row["behavior"]})')
            if s.get('fabricated_citations'):
                reasons.append('fabricated citations: ' + ', '.join(s['fabricated_citations'][:3]))
            if s['forbidden_hit']:
                reasons.append('forbidden phrase')
            if s['leaked']:
                reasons.append('SECRET LEAK')
            lines.append(f'- `{row["route"]}` `{row["case"]}` — {"; ".join(reasons)}')
    return '\n'.join(lines) + '\n'


def write_reports(out: Path, meta, summaries):
    (out / 'summary.json').write_text(json.dumps(dict(meta=meta, routes=summaries), indent=2))
    (out / 'report.md').write_text(markdown(meta, summaries))
    (out / 'failures.md').write_text(failures(out))
