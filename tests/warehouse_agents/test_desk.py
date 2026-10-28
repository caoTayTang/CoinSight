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
        {'command': 'anomaly', 'symbol': 'SOL'},
        {'command': 'predict', 'symbol': 'SOL'},
        {'command': 'predict', 'question': 'do anything'},
        {'command': 'drift'},
        {'command': 'delete'},
        {'command': 'drift', 'sql': 'drop'},
    ):
        with pytest.raises(ValidationError):
            desk.DeskRequest.model_validate(args)
    assert desk.DeskRequest(command='trade', question='inspect', symbol='ETH').symbol == 'ETH'
    assert desk.DeskRequest(command='predict', symbol='ETH').symbol == 'ETH'
    # Production-disabled; this used to accept the direct anomaly command:
    # assert desk.DeskRequest(command='anomaly', symbol='ETH').symbol == 'ETH'


@pytest.mark.asyncio
async def test_direct_daily_forecast_supports_eth_without_llm(monkeypatch):
    async def support(symbol='BTC'):
        assert symbol == 'ETH'
        return {
            'status': 'ready', 'symbol': symbol,
            'forecast': {
                'direction': 'up', 'predicted_close_q10_usdt': 2900.0,
                'predicted_close_q50_usdt': 3000.0, 'predicted_close_q90_usdt': 3150.0,
                'interval_crosses_zero': True,
                'target_open': '2026-10-23T00:00:00+00:00',
                'target_close': '2026-10-24T00:00:00+00:00',
            },
            'recent_performance': {
                'sample_count': 30, 'directional_accuracy': 0.55, 'relative_mae': 1.03,
            },
        }

    monkeypatch.setattr(desk.tools, 'forecast_support', support)
    result = await desk.execute(desk.DeskRequest(command='predict', symbol='ETH'))
    assert result['llm_calls'] == 0 and 'ETH' in result['answer'] and '55.0%' in result['answer']


@pytest.mark.asyncio
@pytest.mark.skip(reason='experimental anomaly command is disabled in production')
async def test_direct_anomaly_runs_tool_without_llm(monkeypatch):
    async def anomaly(symbol='BTC'):
        assert symbol == 'ETH'
        return {
            'symbol': symbol,
            'hourly': {
                'cutoff': '2026-10-19T13:00:00Z',
                'score': 0.4,
                'threshold': 0.6,
                'is_anomaly': False,
            },
            'daily': {
                'cutoff': '2026-10-19T00:00:00Z',
                'score': 0.7,
                'threshold': 0.6,
                'is_anomaly': True,
            },
            'summary': {'risk_state': 'daily_regime_anomaly'},
        }

    monkeypatch.setattr(desk.tools, 'detect_market_anomaly', anomaly)
    result = await desk.execute(desk.DeskRequest(command='anomaly', symbol='ETH'))
    assert result['llm_calls'] == 0 and result['routing'] == []
    assert 'ETH' in result['answer'] and 'daily regime anomaly' in result['answer']


def test_direct_answers_use_plain_words_and_plain_times():
    forecast = desk.forecast_answer(dict(
        expected_move_pct=0.052, predicted_close_usdt=81012.4, reference_close_usdt=80970.0,
        target_close='2026-10-24T07:00:00+00:00', cutoff='2026-10-24T06:00:00+00:00', target_already_started=True,
        research_test={'directional_accuracy_pct': 52.96}, predicted_log_return=0.00052))
    assert 'rise about 0.05% to 81,012.40 USDT by 2026-10-24T07:00:00+00:00' in forecast
    assert 'log return' not in forecast and '`' not in forecast and 'already started' in forecast
    health = desk.health_answer({'drift_watch': False, 'forecast_drift': {'status': 'available', 'flagged': [],
        'features_checked': 30}, 'live_performance': {'reliable': False, 'windows': [], 'ledger': {'scored': 13}}})
    assert 'PSI' not in health and 'Too few recent hours' in health and '13 scored' in health


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
        assert r.status_code == 422 and 'SECRET_KEY' not in r.text


def test_models_lists_routes_with_key_counts(monkeypatch):
    from warehouse_agents import desk

    monkeypatch.setenv('GROQ_API_KEY', '["one-key-xxxxxxxxxxxxxxxx", "two-key-xxxxxxxxxxxxxxxx"]')
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    listed = {r['name']: r for r in desk.models()['routes']}
    assert listed['groq']['keys'] == 2 and listed['groq']['available'] and listed['groq']['label']
    assert listed['openrouter-gemma']['available'] is False
    assert 'one-key' not in str(listed)


def test_desk_request_carries_history_model_and_user():
    from warehouse_agents.desk import DeskRequest

    request = DeskRequest(
        command='sre',
        question='q',
        model='groq',
        user='u_0123456789abcdef',
        history=[{'role': 'user', 'text': 'a'}],
    )
    assert request.history[0].role == 'user'
    for bad in (
        {'model': 'x y'},
        {'user': 'alice@example.com'},
        {'history': [{'role': 'system', 'text': 'x'}]},
    ):
        with pytest.raises(ValueError):
            DeskRequest(command='sre', question='q', **bad)
