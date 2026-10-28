import pytest
from warehouse_agents import skills
from warehouse_agents.graph import ANALYST, OPS, SPECS


def test_catalog_is_valid_and_in_the_tool_schema():
    names = skills.names()
    assert {'missing-candles', 'warehouse-reconciliation', 'incident-report'} <= set(names)
    assert 'model-drift' not in names
    assert SPECS['load_skill']['toolSpec']['inputSchema']['json']['properties']['name']['enum'] == names
    assert 'load_skill' in OPS and 'load_skill' in ANALYST
    for name in names:
        assert f'- {name}: ' in skills.prompt_section()


def test_load_skill_returns_instructions_with_identity():
    result = skills.load('missing-candles')
    assert result['status'] == 'available' and result['citation'] == '[skill:missing-candles]'
    assert '## Report' in result['instructions'] and len(result['sha256']) == 64
    assert skills.load('model-drift')['status'] == 'unavailable'
    assert skills.load('rm -rf')['status'] == 'unavailable'


def test_frontmatter_is_required():
    with pytest.raises(ValueError):
        skills.parse('# no frontmatter')
    meta, body = skills.parse('---\nname: x\ndescription: d\n---\nBody')
    assert meta == {'name': 'x', 'description': 'd'} and body == 'Body'


def test_citations_bound_to_loaded_skills():
    loaded = [{'tool': 'load_skill', 'result': skills.load('missing-candles')}]
    assert skills.validate_citations('Per [skill:missing-candles].', loaded) == ('Per [skill:missing-candles].', [])
    answer, unknown = skills.validate_citations(
        'The service is unavailable. See [skill:service-unreachable].', loaded
    )
    assert unknown == ['[skill:service-unreachable]']
    assert 'The service is unavailable.' in answer and '[skill:service-unreachable]' not in answer


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
