import copy
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from warehouse_agents.anomaly import FEATURES, features, score, read_record, MODEL_DIR, population_shift
from warehouse_agents.graph import Reasoner


@pytest.fixture
def raw():
    n = 210
    rng = np.random.default_rng(42)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    return pd.DataFrame(
        {
            'open_time': pd.date_range('2026-01-01', periods=n, freq='h', tz='UTC'),
            'open_price': close,
            'high_price': close * 1.01,
            'low_price': close * 0.99,
            'close_price': close * 1.001,
            'volume_quote': rng.uniform(10000, 20000, n),
            'trade_count': rng.integers(100, 200, n),
        }
    )


def test_causality_and_minimum_history(raw):
    full = features(raw)
    assert full.iloc[:168].isna().all().all()
    assert full.iloc[168:].notna().all().all()
    pd.testing.assert_frame_equal(full.iloc[:185], features(raw.iloc[:185]))
    changed = raw.copy()
    changed.loc[185:, 'close_price'] *= 2
    pd.testing.assert_frame_equal(full.iloc[:185], features(changed).iloc[:185])


def test_gap_is_not_filled(raw):
    gapped = raw.drop(index=170)
    assert features(gapped).iloc[170:].isna().all().all()


def test_artifact_integrity(tmp_path):
    p = tmp_path / 'record.json'
    p.write_text(json.dumps({'payload': {'a': 1}, 'sha256': 'wrong'}))
    with pytest.raises(ValueError, match='checksum'):
        read_record(p)


def test_frozen_reload_score_and_threshold(raw):
    if not (MODEL_DIR / 'model.json').exists():
        pytest.skip('Frozen model not installed')
    a, b = score(raw), score(raw.copy())
    assert a == b
    assert a['is_anomaly'] == (a['score'] >= a['threshold'])
    assert a['cutoff'] == '2026-01-09T18:00:00+00:00'
    with pytest.raises(ValueError):
        score(raw.iloc[:168])


def test_test_report_reconciles():
    if not (MODEL_DIR / 'test_scores.csv').exists():
        pytest.skip('Research report not installed')
    report = read_record(MODEL_DIR / 'report.json')
    scores = pd.read_csv(MODEL_DIR / 'test_scores.csv')
    assert len(scores) == report['test_n'] == 6984
    assert int(scores.flagged.sum()) == report['test_alerts'] == 78
    assert int(scores.mad_flagged.sum()) == report['mad_test_alerts'] == 101
    assert sum(v['forest_alerts'] for v in report['monthly']) == 78
    assert (
        hashlib.sha256((MODEL_DIR / 'test_scores.csv').read_bytes()).hexdigest()
        == report['test_scores_sha256']
    )
    assert report['accuracy'] is None


class FakeBackend:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def converse(self, **request):
        self.requests.append(copy.deepcopy(request))
        return {
            'output': {'message': {'role': 'assistant', 'content': next(self.responses)}},
            'usage': {'inputTokens': 3},
        }


def use(name, args=None):
    return [{'toolUse': {'toolUseId': 't1', 'name': name, 'input': args or {}}}]


@pytest.mark.asyncio
async def test_graph_chooses_tool_then_answers():
    async def status():
        return {'status': 'unavailable', 'observed_at': 'now'}

    backend = FakeBackend([use('warehouse_status'), [{'text': 'Warehouse unavailable.'}]])
    result = await Reasoner('operations', backend, {'warehouse_status': status}).run('Check warehouse')
    assert result['llm_calls'] == 2 and result['usage']['inputTokens'] == 6
    assert result['evidence'][0]['result']['status'] == 'unavailable'
    assert 'could not be verified' in result['answer']
    assert result['guardrails']['evidence_status'] == 'unavailable'
    assert backend.requests[1]['messages'][-1]['content'][0]['toolResult']['status'] == 'success'


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'name,args',
    [
        ('delete_database', {}),
        ('warehouse_coverage', {'hours': 10000}),
        ('warehouse_coverage', {'sql': 'drop table anything'}),
    ],
)
async def test_unallowed_or_invalid_tools_never_execute(name, args):
    async def forbidden(**kwargs):
        pytest.fail('Invalid tool executed')

    backend = FakeBackend([use(name, args), [{'text': 'Evidence unavailable.'}]])
    result = await Reasoner('operations', backend, {'warehouse_coverage': forbidden}).run('check')
    assert result['evidence'][0]['result']['status'] == 'unavailable'


@pytest.mark.asyncio
async def test_loop_budget():
    async def status():
        return {'status': 'available'}

    result = await Reasoner(
        'operations', FakeBackend([use('warehouse_status')] * 4), {'warehouse_status': status}, max_calls=2
    ).run('Loop')
    assert result['llm_calls'] == 2
    assert 'budget exhausted' in result['answer']


@pytest.mark.asyncio
async def test_full_default_budget_with_a_skill_step_ends_in_an_answer_not_a_crash():
    # Regression: LangGraph's recursion limit was 12, below what 6 tool steps plus a free skill step need, so an
    # investigation that used its whole budget raised GraphRecursionError instead of answering (eval eth_incident.0).
    async def status():
        return {'status': 'available'}

    skill = [{'toolUse': {'toolUseId': 's', 'name': 'load_skill', 'input': {'name': 'missing-candles'}}}]
    tools = {'warehouse_status': status, 'load_skill': __import__('warehouse_agents.tools', fromlist=['x']).load_skill}
    backend = FakeBackend([skill] + [use('warehouse_status')] * 12)
    result = await Reasoner('operations', backend, tools).run('Investigate everything')
    assert result['llm_calls'] == 7 and 'budget exhausted' in result['answer']


@pytest.mark.asyncio
async def test_sensitive_tool_exception_redacted():
    async def broken():
        raise RuntimeError('postgresql://user:secret@host')

    result = await Reasoner(
        'operations',
        FakeBackend([use('warehouse_status'), [{'text': 'Unavailable'}]]),
        {'warehouse_status': broken},
    ).run('Check')
    assert 'secret' not in json.dumps(result)


def test_empty_drift_is_rejected():
    with pytest.raises(ValueError, match='nonempty finite'):
        population_shift(pd.DataFrame(columns=FEATURES), {})


def test_model_plan_binding_and_binary_checksum(monkeypatch, tmp_path):
    import shutil
    import warehouse_agents.anomaly as anomaly

    if not (MODEL_DIR / 'model.json').exists():
        pytest.skip('Frozen model not installed')
    for name in ('model.json', 'plan.json', 'isolation_forest.joblib'):
        shutil.copy2(MODEL_DIR / name, tmp_path / name)
    monkeypatch.setattr(anomaly, 'MODEL_DIR', tmp_path)
    anomaly.load_model.cache_clear()
    try:
        anomaly.load_model()
        anomaly.load_model.cache_clear()
        with (tmp_path / 'isolation_forest.joblib').open('ab') as f:
            f.write(b'corrupt')
        with pytest.raises(ValueError, match='artifact mismatch'):
            anomaly.load_model()
    finally:
        anomaly.load_model.cache_clear()


def test_coverage_default_matches_real_archive_source():
    import ast
    import inspect
    from warehouse_agents.tools import warehouse_coverage

    tree = ast.parse(Path('pipeline/batch/staging_writer.py').read_text())
    source = next(
        ast.literal_eval(n.value)
        for n in tree.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == 'SOURCE_CODE' for t in n.targets)
    )
    assert inspect.signature(warehouse_coverage).parameters['source_code'].default == source


@pytest.mark.asyncio
async def test_trace_endpoint_rejects_bad_ids_and_hides_jaeger_errors(monkeypatch):
    from warehouse_agents import desk, traces

    class Request:
        def __init__(self, trace_id):
            self.path_params = {'trace_id': trace_id}

    assert (await desk.trace_endpoint(Request('../../etc'))).status_code == 422

    async def down(_trace_id):
        raise ConnectionError('http://jaeger:16686 refused')

    monkeypatch.setattr(traces, 'inspect_trace', down)
    body = json.loads((await desk.trace_endpoint(Request('a' * 32))).body)
    assert body['status'] == 'unavailable' and 'jaeger:16686' not in json.dumps(body)
