import pytest
from warehouse_agents.retrieval import search, documents, validate_citations
from warehouse_agents.graph import OPS


@pytest.mark.parametrize(
    'question,source',
    [
        ('container down connection refusal unreachable', 'service_unreachable'),
        ('PSI drift reference distribution', 'feature_drift'),
        ('missing candles closed UTC hours stale', 'missing_candles'),
        ('accounting_delta staging rejected duplicate accepted', 'reconciliation'),
        ('secrets credentials prompt instructions', 'security'),
    ],
)
def test_ranked_evidence(question, source):
    result = search(question, mode='bm25')
    assert result['status'] == 'available'
    assert source in result['hits'][0]['source']
    assert len(result['hits'][0]['sha256']) == 64


def test_unknown_and_bounds():
    assert search('zzzzquuxxy', mode='bm25')['status'] == 'unavailable'
    for query, k in [('', 3), ('x' * 2001, 3), ('PSI', 0), ('PSI', True)]:
        with pytest.raises(ValueError):
            search(query, k)
    with pytest.raises(ValueError):
        search('PSI', mode='invented')


def test_sources_allowlisted_and_citations_bound_to_returned_hits():
    assert all('/knowledge/' in d['source'] and len(d['text']) <= 1600 for d in documents())
    result = search('PSI drift', mode='bm25')
    citation = result['hits'][0]['citation']
    evidence = [{'tool': 'search_runbooks', 'result': result}]
    assert validate_citations('See ' + citation, evidence) == ('See ' + citation, [])
    answer, unknown = validate_citations('[runbook:made_up:0:0]', evidence)
    assert unknown and 'could not be verified' in answer
    assert validate_citations(citation, [])[1]


def test_neural_backend_cannot_silently_fallback(monkeypatch):
    from warehouse_agents import retrieval

    def unavailable():
        raise RuntimeError('Model missing')

    monkeypatch.setattr(retrieval, 'neural_index', unavailable)
    with pytest.raises(RuntimeError):
        search('drift', mode='hybrid')


def test_sre_can_observe_drift_and_retrieve():
    assert 'model_health' in OPS and 'search_runbooks' in OPS


@pytest.mark.asyncio
async def test_graph_rejects_fabricated_source():
    from warehouse_agents.graph import Reasoner

    class Backend:
        async def converse(self, **kwargs):
            return {
                'output': {
                    'message': {'role': 'assistant', 'content': [{'text': 'Restart it [runbook:fake:0:0]'}]}
                }
            }

    result = await Reasoner('operations', Backend()).run('Explain an outage')
    assert result['guardrails']['invalid_citations'] == ['[runbook:fake:0:0]']
    assert 'could not be verified' in result['answer']


def test_unverified_citation_is_stripped_and_answer_kept():
    answer, unknown = validate_citations('BTC is missing 3 hours. See [runbook:made_up:0:0].', [])
    assert unknown == ['[runbook:made_up:0:0]']
    assert 'BTC is missing 3 hours.' in answer and '[runbook:made_up' not in answer
