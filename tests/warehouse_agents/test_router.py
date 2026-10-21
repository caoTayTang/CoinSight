import asyncio
import json
import httpx
import pytest
from warehouse_agents.router import Router, RouterUnavailable, chat_request, chat_response

REQUEST = {
    'system': [{'text': 'Read-only.'}],
    'messages': [{'role': 'user', 'content': [{'text': 'Check'}]}],
    'inferenceConfig': {'maxTokens': 100, 'temperature': 0},
}


def config():
    return {
        'routes': [
            {
                'name': 'first',
                'provider': 'bedrock',
                'model': 'us.amazon.nova-2-lite-v1:0',
                'api_key_env': 'TEST_FIRST_KEY',
            },
            {'name': 'second', 'provider': 'groq', 'model': 'test-model', 'api_key_env': 'TEST_SECOND_KEY'},
            {
                'name': 'third',
                'provider': 'openrouter',
                'model': 'test-model-2',
                'api_key_env': 'TEST_THIRD_KEY',
            },
        ]
    }


def reply(text='ok'):
    return {
        'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': text}}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 2},
    }


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    for name in ('FIRST', 'SECOND', 'THIRD'):
        monkeypatch.setenv('TEST_' + name + '_KEY', name.lower() + '-secret')


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [400, 401, 402, 403, 404, 408, 422, 429, 500, 502, 503, 504])
async def test_failover_http_errors_and_preserve_payload(status):
    seen = []

    def respond(request):
        seen.append(request)
        return (
            httpx.Response(status, json={'secret': 'DO NOT LOG'})
            if 'amazonaws' in request.url.host
            else httpx.Response(200, json=reply())
        )

    r = await Router(config(), httpx.MockTransport(respond)).converse(**REQUEST)
    assert len(seen) == 2
    assert seen[0].headers['authorization'] == 'Bearer first-secret'
    assert seen[1].headers['authorization'] == 'Bearer second-secret'
    assert r['routing']['selected']['provider'] == 'groq'
    assert r['routing']['attempts'][0]['http_status'] == status
    assert r['output']['message']['content'] == [{'text': 'ok'}]
    assert r['usage']['inputTokens'] == 10
    assert 'secret' not in json.dumps(r)
    assert json.loads(seen[1].content)['messages'][1]['content'] == 'Check'


@pytest.mark.asyncio
async def test_cooldown_skips_failed_route_until_expiry():
    seen = []

    def respond(request):
        seen.append(request.url.host)
        return httpx.Response(429) if 'amazonaws' in request.url.host else httpx.Response(200, json=reply())

    router = Router(config(), httpx.MockTransport(respond))
    await router.converse(**REQUEST)
    second = await router.converse(**REQUEST)
    assert len(seen) == 3
    assert second['routing']['attempts'][0]['status'] == 'cooldown'
    router.cooldowns['first'] = 0
    await router.converse(**REQUEST)
    assert len(seen) == 5


@pytest.mark.asyncio
async def test_missing_keys_skipped_and_exhaustion_sanitized(monkeypatch):
    for name in ('FIRST', 'SECOND', 'THIRD'):
        monkeypatch.delenv('TEST_' + name + '_KEY')

    def forbidden(request):
        pytest.fail('Request sent without key')

    with pytest.raises(RouterUnavailable) as exc:
        await Router(config(), httpx.MockTransport(forbidden)).converse(**REQUEST)
    assert len(exc.value.attempts) == 3
    assert all(a['status'] == 'missing_key' for a in exc.value.attempts)
    assert 'secret' not in str(exc.value)


@pytest.mark.asyncio
async def test_network_timeout_then_malformed_then_openrouter():
    def respond(request):
        if 'amazonaws' in request.url.host:
            raise httpx.ReadTimeout('secret content', request=request)
        if 'groq' in request.url.host:
            return httpx.Response(200, json={'choices': []})
        return httpx.Response(200, json=reply())

    r = await Router(config(), httpx.MockTransport(respond)).converse(**REQUEST)
    assert r['routing']['selected']['provider'] == 'openrouter'
    assert len(r['routing']['attempts']) == 3
    assert 'secret' not in json.dumps(r)


def test_tool_history_round_trip_cross_provider():
    response = chat_response(
        {
            'choices': [
                {
                    'finish_reason': 'tool_calls',
                    'message': {
                        'content': None,
                        'tool_calls': [
                            {
                                'id': 'call-123',
                                'function': {'name': 'warehouse_coverage', 'arguments': '{"hours":24}'},
                            }
                        ],
                    },
                }
            ]
        }
    )
    request = dict(
        REQUEST,
        messages=REQUEST['messages']
        + [
            response['output']['message'],
            {
                'role': 'user',
                'content': [
                    {
                        'toolResult': {
                            'toolUseId': 'call-123',
                            'status': 'error',
                            'content': [{'json': {'status': 'unavailable'}}],
                        }
                    }
                ],
            },
        ],
        toolConfig={
            'tools': [
                {
                    'toolSpec': {
                        'name': 'warehouse_coverage',
                        'description': 'Coverage',
                        'inputSchema': {'json': {'type': 'object'}},
                    }
                }
            ]
        },
    )
    result = chat_request(request, 'backup-model')
    assert result['messages'][-2]['tool_calls'][0]['id'] == 'call-123'
    assert result['messages'][-1]['tool_call_id'] == 'call-123'
    assert json.loads(result['messages'][-1]['content'])['status'] == 'error'
    assert result['tools'][0]['function']['name'] == 'warehouse_coverage'


@pytest.mark.parametrize(
    'body',
    [
        {'choices': [{'finish_reason': 'length', 'message': {'content': 'partial'}}]},
        {'error': {'message': 'secret'}},
        {'choices': [{'message': {'content': None}}]},
        {
            'choices': [
                {'message': {'tool_calls': [{'id': 'x', 'function': {'name': 'x', 'arguments': '[1]'}}]}}
            ]
        },
    ],
)
def test_invalid_model_responses_rejected(body):
    with pytest.raises(ValueError):
        chat_response(body)


def test_config_rejects_plaintext_key_and_duplicate_names():
    c = config()
    c['routes'][0]['api_key'] = 'do-not-store-keys-here'
    with pytest.raises(ValueError):
        Router(c)
    c = config()
    c['routes'][1]['name'] = 'first'
    with pytest.raises(ValueError):
        Router(c)


@pytest.mark.asyncio
async def test_total_deadline_bounds_all_attempts():
    async def slow(request):
        await asyncio.sleep(2)
        return httpx.Response(200, json=reply())

    c = config()
    c['total_timeout_seconds'] = 1
    with pytest.raises(RouterUnavailable) as exc:
        await Router(c, httpx.MockTransport(slow)).converse(**REQUEST)
    assert exc.value.attempts[-1]['status'] == 'total_deadline'


@pytest.mark.asyncio
async def test_same_provider_second_key():
    c = config()
    c['routes'] = [dict(c['routes'][1], name='groq-key-1', api_key_env='TEST_FIRST_KEY'), c['routes'][1]]
    seen = []

    def respond(request):
        seen.append(request.headers['authorization'])
        return httpx.Response(401) if len(seen) == 1 else httpx.Response(200, json=reply())

    r = await Router(c, httpx.MockTransport(respond)).converse(**REQUEST)
    assert seen == ['Bearer first-secret', 'Bearer second-secret']
    assert r['routing']['selected']['route'] == 'second'


@pytest.mark.asyncio
async def test_reasoner_continues_tool_loop_after_provider_failover():
    from warehouse_agents.graph import Reasoner

    tool_requests = []

    def respond(request):
        if 'amazonaws' in request.url.host:
            return httpx.Response(503)
        body = json.loads(request.content)
        tool_requests.append(body)
        if len(tool_requests) == 1:
            return httpx.Response(
                200,
                json={
                    'choices': [
                        {
                            'finish_reason': 'tool_calls',
                            'message': {
                                'content': None,
                                'tool_calls': [
                                    {
                                        'id': 'stable-id',
                                        'function': {'name': 'warehouse_status', 'arguments': '{}'},
                                    }
                                ],
                            },
                        }
                    ]
                },
            )
        assert body['messages'][-1]['role'] == 'tool'
        assert body['messages'][-1]['tool_call_id'] == 'stable-id'
        return httpx.Response(200, json=reply('Evidence unavailable.'))

    async def evidence():
        return {'status': 'unavailable'}

    result = await Reasoner(
        'operations', Router(config(), httpx.MockTransport(respond)), {'warehouse_status': evidence}
    ).run('Check')
    assert result['llm_calls'] == 2
    assert 'could not be verified' in result['answer']
    assert result['guardrails']['evidence_status'] == 'unavailable'
    assert len(result['evidence']) == 1
    assert result['routing'][0]['selected']['provider'] == 'groq'
    assert result['routing'][1]['attempts'][0]['status'] == 'cooldown'
    first, second = result['steps']
    # Step 1: Bedrock failed over to Groq, which called one tool; the tool's output is evidence[0].
    assert first['model']['route'] == 'second' and first['fallbacks'][0]['route'] == 'first'
    assert first['tools'] == [
        {
            'name': 'warehouse_status',
            'arguments': {},
            'status': 'success',
            'latency_ms': first['tools'][0]['latency_ms'],
            'evidence': 0,
        }
    ]
    assert result['evidence'][first['tools'][0]['evidence']]['tool'] == 'warehouse_status'
    assert second['tools'] == [] and second['text'] == 'Evidence unavailable.'
    assert first['usage'] == {'inputTokens': 0, 'outputTokens': 0} and second['usage'] == {
        'inputTokens': 10,
        'outputTokens': 2,
    }


def test_bad_config_does_not_echo_accidental_plaintext_key():
    c = config()
    c['routes'][0]['api_key'] = 'VERY_PRIVATE_KEY'
    with pytest.raises(ValueError) as exc:
        Router(c)
    assert 'VERY_PRIVATE_KEY' not in str(exc.value)


def test_server_rejects_invalid_router_config_at_startup(monkeypatch, tmp_path):
    from warehouse_agents.server import create_app

    path = tmp_path / 'invalid.json'
    path.write_text('{"routes": []}')
    monkeypatch.setenv('LLM_ROUTER_CONFIG', str(path))
    with pytest.raises(ValueError, match='Invalid router configuration'):
        create_app('operations')


@pytest.mark.asyncio
async def test_round_robin_rotates_every_call():
    c = config()
    c['strategy'] = 'round_robin'
    c['routes'] = [dict(r, provider='groq') for r in c['routes']]

    def respond(request):
        return httpx.Response(200, json=reply())

    router = Router(c, httpx.MockTransport(respond))
    selected = [(await router.converse(**REQUEST))['routing']['selected']['route'] for _ in range(7)]
    assert selected == ['first', 'second', 'third', 'first', 'second', 'third', 'first']


@pytest.mark.asyncio
async def test_round_robin_skips_missing_and_cooled_routes(monkeypatch):
    c = config()
    c['strategy'] = 'round_robin'
    c['routes'] = [dict(r, provider='groq') for r in c['routes']]
    monkeypatch.delenv('TEST_SECOND_KEY')
    router = Router(c, httpx.MockTransport(lambda r: httpx.Response(200, json=reply())))
    selected = [(await router.converse(**REQUEST))['routing']['selected']['route'] for _ in range(4)]
    assert selected == ['first', 'third', 'first', 'third']
    router.cooldowns['first'] = __import__('time').monotonic() + 30
    assert (await router.converse(**REQUEST))['routing']['selected']['route'] == 'third'


@pytest.mark.asyncio
async def test_round_robin_concurrent_calls_reserve_distinct_starts():
    c = config()
    c['strategy'] = 'round_robin'
    c['routes'] = [dict(r, provider='groq') for r in c['routes']]

    async def respond(request):
        await asyncio.sleep(0.01)
        return httpx.Response(200, json=reply())

    router = Router(c, httpx.MockTransport(respond))
    results = await asyncio.gather(*(router.converse(**REQUEST) for _ in range(3)))
    assert [r['routing']['selected']['route'] for r in results] == ['first', 'second', 'third']


@pytest.mark.asyncio
async def test_round_robin_failure_falls_through_and_next_call_skips_cooldown():
    c = config()
    c['strategy'] = 'round_robin'
    c['routes'] = [dict(r, provider='groq') for r in c['routes']]

    def respond(request):
        return (
            httpx.Response(429)
            if request.headers['authorization'] == 'Bearer first-secret'
            else httpx.Response(200, json=reply())
        )

    router = Router(c, httpx.MockTransport(respond))
    first = await router.converse(**REQUEST)
    assert first['routing']['selected']['route'] == 'second'
    assert first['routing']['attempts'][0]['http_status'] == 429
    assert (await router.converse(**REQUEST))['routing']['selected']['route'] == 'second'
    assert (await router.converse(**REQUEST))['routing']['selected']['route'] == 'third'
    assert (await router.converse(**REQUEST))['routing']['selected']['route'] == 'second'


def tiered(monkeypatch):
    """One Groq route holding three keys (rotating slots in tier 0), OpenRouter in tier 1, Bedrock last."""
    monkeypatch.setenv('TEST_GROQ_KEYS', '["groq-key-1", "groq-key-2", "groq-key-3"]')
    return {
        'strategy': 'round_robin',
        'routes': [
            {'name': 'groq', 'provider': 'groq', 'model': 'gpt-oss', 'api_key_env': 'TEST_GROQ_KEYS'},
            {
                'name': 'openrouter',
                'provider': 'openrouter',
                'model': 'm',
                'api_key_env': 'TEST_THIRD_KEY',
                'tier': 1,
            },
            {
                'name': 'haiku',
                'provider': 'bedrock',
                'model': 'h',
                'api_key_env': 'TEST_FIRST_KEY',
                'tier': 2,
            },
        ],
    }


@pytest.mark.asyncio
async def test_key_list_slots_rotate_within_first_tier_and_never_start_on_fallbacks(monkeypatch):
    used = []

    def respond(request):
        used.append(request.headers['authorization'])
        return httpx.Response(200, json=reply())

    router = Router(tiered(monkeypatch), httpx.MockTransport(respond))
    selected = [(await router.converse(**REQUEST))['routing']['selected']['route'] for _ in range(5)]
    assert selected == ['groq#1', 'groq#2', 'groq#3', 'groq#1', 'groq#2']
    assert used[:3] == ['Bearer groq-key-1', 'Bearer groq-key-2', 'Bearer groq-key-3']


@pytest.mark.asyncio
async def test_tier_fallback_order_and_retry_after_cooldown(monkeypatch):
    def respond(request):
        if request.url.host == 'api.groq.com':
            return httpx.Response(429, headers={'retry-after': '171'})
        if request.url.host == 'openrouter.ai':
            return httpx.Response(503)
        return httpx.Response(
            200, json={'output': {'message': {'role': 'assistant', 'content': [{'text': 'ok'}]}}}
        )

    router = Router(tiered(monkeypatch), httpx.MockTransport(respond))
    result = await router.converse(**REQUEST)
    attempts = result['routing']['attempts']
    assert [a['route'] for a in attempts] == ['groq#1', 'groq#2', 'groq#3', 'openrouter', 'haiku']
    assert result['routing']['selected'] == {'route': 'haiku', 'provider': 'bedrock', 'model': 'h', 'tier': 2}
    # Groq asked for 171 s, longer than the 30 s default; OpenRouter gave no Retry-After.
    assert [a.get('cooldown_seconds') for a in attempts[:4]] == [171, 171, 171, 30]
    again = await router.converse(**REQUEST)
    assert [a['status'] for a in again['routing']['attempts']][:4] == ['cooldown'] * 4


@pytest.mark.asyncio
async def test_retry_after_is_capped():
    c = config()
    router = Router(c, httpx.MockTransport(lambda r: httpx.Response(429, headers={'retry-after': '999999'})))
    with pytest.raises(RouterUnavailable) as raised:
        await router.converse(**REQUEST)
    assert {a['cooldown_seconds'] for a in raised.value.attempts} == {3600}


def test_reasoning_kept_beside_message_not_in_it():
    body = reply('done')
    body['choices'][0]['message']['reasoning'] = 'Check coverage first.'
    result = chat_response(body)
    assert result['reasoning'] == 'Check coverage first.'
    assert result['output']['message']['content'] == [{'text': 'done'}]
    body['choices'][0]['message'] = {
        'role': 'assistant',
        'content': 'x',
        'reasoning_content': ' ' * 3 + 'q' * 5000,
    }
    assert len(chat_response(body)['reasoning']) == 4000


@pytest.mark.parametrize('value', ['["a", "b"]', 'a, b', ' a,b, ', "['a','b']"])
def test_key_list_formats(value):
    from warehouse_agents.guardrails import split_keys

    assert split_keys(value) == ['a', 'b']
    assert split_keys('single-key') == ['single-key'] and split_keys('') == []
