"""Measure how often the scorer's behaviour verdicts agree with a human.

1. Export a labeling sheet:   python -m evals.calibrate export evals/reports/val-v1 labels.csv
2. Open it in a spreadsheet. Fill "human_ok" with y/n (did the agent behave correctly?), add a note if useful.
   Label before looking at "scorer_ok". Keep the file as CSV when saving.
3. Compare:                   python -m evals.calibrate compare evals/reports/val-v1 labels.csv

A .jsonl sheet works the same way, with human_ok set to true/false.

Reports raw agreement and Cohen's kappa, and lists disagreements to fix in the scorer or the labels.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def rows(out):
    for path in sorted(Path(out).glob('results-*.jsonl')):
        yield from map(json.loads, path.read_text().splitlines())


FIELDS = ('route', 'case', 'behavior', 'question', 'answer', 'tools', 'human_ok', 'note', 'scorer_ok')
YES, NO = ('y', 'yes', 'true', '1'), ('n', 'no', 'false', '0')


def export(out, labels):
    sheet = [
        {
            'route': row['route'],
            'case': row['case'],
            'behavior': row['behavior'],
            'question': row['question'],
            'answer': row['answer'],
            'tools': ', '.join(e['tool'] for e in row['evidence']),
            'human_ok': None,
            'note': '',
            'scorer_ok': row['score']['passed'],
        }
        for row in rows(out)
    ]
    path = Path(labels)
    if path.suffix == '.csv':
        # utf-8-sig so spreadsheet apps show Vietnamese correctly.
        with path.open('w', newline='', encoding='utf-8-sig') as handle:
            writer = csv.DictWriter(handle, FIELDS)
            writer.writeheader()
            writer.writerows({**r, 'human_ok': ''} for r in sheet)
        return
    with path.open('w') as handle:
        for r in sheet:
            handle.write(json.dumps(r, ensure_ascii=False) + '\n')


def _label(value):
    """true/false/None from a JSON bool or a spreadsheet cell (y/n, yes/no, true/false, 1/0, blank)."""
    if value is None or isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in YES:
        return True
    if text in NO:
        return False
    if text:
        raise SystemExit(f'Unrecognised human_ok value {value!r}; use y or n')
    return None


def read_labels(labels):
    path = Path(labels)
    if path.suffix == '.csv':
        with path.open(newline='', encoding='utf-8-sig') as handle:
            return list(csv.DictReader(handle))
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def kappa(pairs):
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    p_a, p_b = sum(a for a, _ in pairs) / n, sum(b for _, b in pairs) / n
    expected = p_a * p_b + (1 - p_a) * (1 - p_b)
    return (observed - expected) / (1 - expected) if expected < 1 else 1.0


def compare(out, labels):
    scored = {(r['route'], r['case']): r['score']['passed'] for r in rows(out)}
    pairs, disagreements = [], []
    for label in read_labels(labels):
        human = _label(label['human_ok'])
        if human is None:
            continue
        machine = scored[(label['route'], label['case'])]
        pairs.append((machine, human))
        if machine != human:
            disagreements.append(
                f'{label["route"]} {label["case"]}: scorer={machine} human={human} {label.get("note", "")}'
            )
    if not pairs:
        raise SystemExit('No labeled rows (fill human_ok with y or n)')
    agreement = sum(a == b for a, b in pairs) / len(pairs)
    print(
        json.dumps(
            {'labeled': len(pairs), 'agreement': round(agreement, 4), 'cohens_kappa': round(kappa(pairs), 4)}
        )
    )
    for line in disagreements:
        print('  ' + line)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('action', choices=('export', 'compare'))
    parser.add_argument('out')
    parser.add_argument('labels')
    args = parser.parse_args()
    (export if args.action == 'export' else compare)(args.out, args.labels)


if __name__ == '__main__':
    main()
