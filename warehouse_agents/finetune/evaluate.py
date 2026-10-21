"""Score precomputed held-out predictions without executing model-selected tools."""

import argparse, json
from pathlib import Path
from warehouse_agents.finetune.train import load_dataset


def evaluate(data, predictions):
    test = {r['scenario_id']: r for r in data if r['split'] == 'test'}
    if len(test) != sum(r['split'] == 'test' for r in data):
        raise ValueError('Evaluator requires one held-out question per scenario ID')
    if set(test) != set(predictions):
        raise ValueError('Predictions must cover exactly the held-out scenarios')
    valid = tool = exact = 0
    for key, r in test.items():
        try:
            value = predictions[key]
            if isinstance(value, str):
                value = json.loads(value)
            if not isinstance(value, dict):
                continue
            valid += 1
            tool += value.get('tool') == r['target']['tool']
            exact += value == r['target']
        except (ValueError, TypeError):
            continue
    n = len(test)
    return dict(
        n=n,
        json_object_rate=valid / n,
        tool_accuracy=tool / n,
        exact_match=exact / n,
        limitations='Offline action selection; no tools executed; not end-to-end SRE success.',
    )


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--data', required=True)
    p.add_argument('--predictions', required=True)
    a = p.parse_args()
    print(json.dumps(evaluate(load_dataset(a.data), json.loads(Path(a.predictions).read_text())), indent=2))
