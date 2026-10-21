import json
from pathlib import Path
import pytest
from warehouse_agents.finetune.train import load_dataset
from warehouse_agents.finetune.evaluate import evaluate

SEED = Path('warehouse_agents/finetune/seed.jsonl')


def test_split_leakage_rejected(tmp_path):
    rows = load_dataset(SEED)
    rows[-1]['scenario_id'] = rows[0]['scenario_id']
    p = tmp_path / 'data.jsonl'
    p.write_text('\n'.join(json.dumps(r) for r in rows))
    with pytest.raises(ValueError, match='leakage'):
        load_dataset(p)


def test_exact_prediction_scoring_and_missing_predictions():
    rows = load_dataset(SEED)
    predictions = {r['scenario_id']: r['target'] for r in rows if r['split'] == 'test'}
    assert evaluate(rows, predictions)['exact_match'] == 1
    predictions['svc-outage'] = 'invalid json'
    assert evaluate(rows, predictions)['json_object_rate'] == 0.75
    with pytest.raises(ValueError):
        evaluate(rows, {})
