import pytest
from warehouse_agents import skills
from warehouse_agents.graph import ANALYST, OPS, SPECS
from warehouse_agents.retrieval import documents, search


def test_catalog_is_valid_and_in_the_tool_schema():
    names = skills.names()
    assert {'missing-candles', 'warehouse-reconciliation', 'model-drift', 'incident-report'} <= set(names)
    assert SPECS['load_skill']['toolSpec']['inputSchema']['json']['properties']['name']['enum'] == names
    assert 'load_skill' in OPS and 'load_skill' in ANALYST
    for name in names:
        assert f'- {name}: ' in skills.prompt_section()


def test_load_skill_returns_instructions_with_identity():
    result = skills.load('missing-candles')
    assert result['status'] == 'available' and result['citation'] == '[skill:missing-candles]'
    assert '## Report' in result['instructions'] and len(result['sha256']) == 64
    assert skills.load('rm -rf')['status'] == 'unavailable'


def test_frontmatter_is_required():
    with pytest.raises(ValueError):
        skills.parse('# no frontmatter')
    meta, body = skills.parse('---\nname: x\ndescription: d\n---\nBody')
    assert meta == {'name': 'x', 'description': 'd'} and body == 'Body'


def test_citations_bound_to_loaded_skills():
    loaded = [{'tool': 'load_skill', 'result': skills.load('model-drift')}]
    assert skills.validate_citations('Per [skill:model-drift].', loaded) == ('Per [skill:model-drift].', [])
    answer, unknown = skills.validate_citations(
        'BTC is missing 3 hours. See [skill:missing-candles].', loaded
    )
    assert unknown == ['[skill:missing-candles]']
    assert 'BTC is missing 3 hours.' in answer and '[skill:missing-candles]' not in answer


@pytest.mark.asyncio
async def test_graph_strips_citation_of_a_skill_it_did_not_load():
    from warehouse_agents.graph import Reasoner

    class Backend:
        async def converse(self, **kwargs):
            assert 'load_skill with its name' in kwargs['system'][0]['text']
            text = 'Restart it [skill:service-unreachable]'
            return {'output': {'message': {'role': 'assistant', 'content': [{'text': text}]}}}

    result = await Reasoner('operations', Backend()).run('Explain an outage')
    assert result['guardrails']['invalid_citations'] == ['[skill:service-unreachable]']
    assert '[unverified citation removed]' in result['answer']


@pytest.mark.parametrize(
    'question,skill',
    [
        ('container down connection refusal unreachable', 'service-unreachable'),
        ('PSI drift reference distribution', 'model-drift'),
        ('missing candles closed UTC hours stale', 'missing-candles'),
        ('accounting_delta staging rejected duplicate accepted', 'warehouse-reconciliation'),
    ],
)
def test_search_ranks_the_right_skill(question, skill):
    result = search(question, mode='bm25')
    assert result['status'] == 'available' and f'/{skill}/' in result['hits'][0]['source']


def test_search_bounds_and_sources():
    assert all('/skills/' in d['source'] and len(d['text']) <= 1600 for d in documents())
    assert search('zzzzquuxxy', mode='bm25')['status'] == 'unavailable'
    for query, k in [('', 3), ('x' * 2001, 3), ('PSI', 0), ('PSI', True)]:
        with pytest.raises(ValueError):
            search(query, k)
    with pytest.raises(ValueError):
        search('PSI', mode='invented')


def test_neural_backend_cannot_silently_fallback(monkeypatch):
    from warehouse_agents import retrieval

    def unavailable():
        raise RuntimeError('Model missing')

    monkeypatch.setattr(retrieval, 'neural_index', unavailable)
    with pytest.raises(RuntimeError):
        search('drift', mode='hybrid')


@pytest.mark.asyncio
async def test_a_skill_only_step_does_not_use_the_budget():
    from warehouse_agents.graph import Reasoner

    calls = []

    class Backend:
        async def converse(self, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                use = {'toolUseId': 's', 'name': 'load_skill', 'input': {'name': 'missing-candles'}}
            elif len(calls) <= 4:
                use = {'toolUseId': f't{len(calls)}', 'name': 'warehouse_status', 'input': {}}
            else:
                return {'output': {'message': {'role': 'assistant', 'content': [{'text': 'done'}]}}}
            return {'output': {'message': {'role': 'assistant', 'content': [{'toolUse': use}]}}}

    async def status():
        return {'status': 'available', 'rows': []}

    tools = {
        'load_skill': __import__('warehouse_agents.tools', fromlist=['x']).load_skill,
        'warehouse_status': status,
    }
    result = await Reasoner('operations', Backend(), tools, max_calls=4).run('Check')
    # 1 skill-only step + 3 tool steps + the answer = 5 model calls with a budget of 4.
    assert result['llm_calls'] == 5 and result['answer'] == 'done'
