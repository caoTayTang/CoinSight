import httpx
import pytest
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.routing import Route
from warehouse_agents import desk
from warehouse_agents.runtime import LocalGuard


def test_command_contract():
    for args in (
        {'command': 'sre'},
        {'command': 'trade'},
        {'command': 'anomaly', 'symbol': 'ETH'},
        {'command': 'predict', 'question': 'do anything'},
        {'command': 'delete'},
        {'command': 'drift', 'sql': 'drop'},
    ):
        with pytest.raises(ValidationError):
            desk.DeskRequest.model_validate(args)
    assert desk.DeskRequest(command='trade', question='inspect', symbol='ETH').symbol == 'ETH'


@pytest.mark.asyncio
async def test_direct_anomaly_runs_tool_without_llm(monkeypatch):
    async def anomaly():
        return {
            'trained': {
                'cutoff': '2026-10-19T13:00:00Z',
                'score': 0.4,
                'threshold': 0.6,
                'is_anomaly': False,
            },
            'mad_baseline': {'is_anomaly': False},
        }

    monkeypatch.setattr(desk.tools, 'detect_market_anomaly', anomaly)
    result = await desk.execute(desk.DeskRequest(command='anomaly'))
    assert result['llm_calls'] == 0 and result['routing'] == [] and 'not flagged' in result['answer']


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'command,role_url', [('trade', 'ANALYST_AGENT_URL'), ('sre', 'OPERATIONS_AGENT_URL')]
)
async def test_public_names_delegate_to_correct_peer(monkeypatch, command, role_url):
    monkeypatch.setenv(role_url, 'http://test-peer')

    async def call(url, payload, **kwargs):
        assert url == 'http://test-peer' and payload['question'] == 'inspect'
        return {
            'task_id': 'task-1',
            'result': {'answer': 'evidence', 'routing': [], 'evidence': [], 'llm_calls': 2},
        }

    monkeypatch.setattr(desk, 'call_agent', call)
    result = await desk.execute(desk.DeskRequest(command=command, question='inspect'))
    assert result['task_id'] == 'task-1' and result['llm_calls'] == 2


@pytest.mark.asyncio
async def test_http_bridge_auth_validation_and_safe_failure(monkeypatch):
    async def broken(request):
        raise RuntimeError('SECRET_KEY')

    monkeypatch.setattr(desk, 'execute', broken)
    app = LocalGuard(
        Starlette(routes=[Route('/desk/command', desk.endpoint, methods=['POST'])]), token='test'
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as c:
        assert (await c.post('/desk/command', json={'command': 'drift'})).status_code == 401
        headers = {'Authorization': 'Bearer test'}
        assert (
            await c.post('/desk/command', json={'command': 'unknown'}, headers=headers)
        ).status_code == 422
        r = await c.post('/desk/command', json={'command': 'drift'}, headers=headers)
        assert r.status_code == 503 and 'SECRET_KEY' not in r.text
