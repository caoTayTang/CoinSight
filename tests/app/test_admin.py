"""Admin console queries against the real schema. Requires an isolated database named admin_test."""

import json
import os
import uuid

import pytest
from fastapi import HTTPException

from app import admin, agent_runs, usage
from app.auth import User, user_key
from app.desk_commands import CommandRequest

DSN = os.getenv('APP_ADMIN_TEST_DSN')
OWNER = 'owner@example.com'
GUEST = User(key='u_' + 'a' * 16, email='guest@example.com')
HAIKU = 'global.anthropic.claude-haiku'
GROQ = 'openai/gpt-oss-120b'


def step(model, latency, tools=(), fallbacks=()):
    return {
        'kind': 'model',
        'model': {'route': model[0] + '#1', 'provider': model[1], 'model': model[2]},
        'fallbacks': list(fallbacks),
        'latency_ms': latency,
        'usage': {'inputTokens': 1000, 'outputTokens': 100},
        'tools': [{'name': t, 'arguments': {}} for t in tools],
    }


GROQ_STEP = ('groq', 'groq', GROQ)
HAIKU_STEP = ('bedrock-haiku', 'bedrock', HAIKU)
FAILED = {'route': 'groq#2', 'model': GROQ, 'status': 'http_error', 'http_status': 429}


def test_admin_is_for_owners_only(monkeypatch):
    monkeypatch.setenv('AGENT_OWNER_EMAILS', OWNER)
    monkeypatch.setattr(agent_runs, 'query', lambda sql, params=(): [])
    with pytest.raises(HTTPException) as refused:
        admin.require_owner(GUEST)
    assert refused.value.status_code == 403
    owner = User(key=user_key(OWNER), email=OWNER)
    assert admin.require_owner(owner) is owner
    assert admin.labels()[user_key(OWNER)] == OWNER


def test_window_is_bounded():
    with pytest.raises(HTTPException):
        admin.window(0)
    with pytest.raises(HTTPException):
        admin.window(admin.MAX_DAYS + 1)


def test_search_text_is_escaped():
    assert admin.like('50%_off') == r'%50\%\_off%'


@pytest.fixture
def seeded(monkeypatch):
    if not DSN:
        pytest.skip('Set APP_ADMIN_TEST_DSN to an isolated database named admin_test')
    monkeypatch.setattr(agent_runs, 'DATABASE_URL', DSN)
    assert agent_runs.query('select current_database() as db')[0]['db'] == 'admin_test'
    agent_runs.query('truncate meta.agent_run, meta.agent_refusal, meta.app_user cascade', fetch=False)
    monkeypatch.setenv('AGENT_OWNER_EMAILS', OWNER)
    monkeypatch.setattr(usage, 'paid_routes', lambda: {'bedrock-haiku': (HAIKU, {'input': 1.0, 'output': 5.0})})
    monkeypatch.setattr(usage, 'gateway', lambda method, path, query=None: {'routes': [
        {'name': 'groq', 'model': GROQ, 'label': 'GPT-OSS 120B', 'eval': {'pass_rate': 0.92}, 'price': None}]})
    owner, guest = user_key(OWNER), GUEST.key
    rows = [
        (owner, 'trade', 'How is BTC?', 'ok', None, [GROQ], [step(GROQ_STEP, 900, ['market_data'])], 1200),
        (owner, 'sre', 'Any missing candles?', 'ok', None, [GROQ],
         [step(GROQ_STEP, 1500, ['warehouse_coverage', 'warehouse_status'], [FAILED])], 3000),
        (guest, 'trade', 'Explain the forecast', 'ok', None, [HAIKU], [step(HAIKU_STEP, 2500, ['predict_hourly'])], 4000),
        (guest, 'sre', 'Is the API down?', 'error', 'gateway timeout', [], [], 60000),
        (guest, 'predict', '', 'ok', None, [], [], 300),
    ]
    ids = []
    for key, command, question, status, error, models, steps, latency in rows:
        run_id = uuid.uuid4()
        ids.append(run_id)
        tokens = 1000 if steps else 0
        agent_runs.query(
            """insert into meta.agent_run (run_id, user_key, thread_id, command, symbol, question, answer, status,
                   error, models, llm_calls, input_tokens, output_tokens, latency_ms, steps)
               values (%s, %s, %s, %s, 'BTC', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (str(run_id), key, str(uuid.uuid4()), command, question, f'Answer to {question}', status, error,
             models, len(steps), tokens, tokens // 10, latency, json.dumps(steps)),
            fetch=False,
        )
    request = CommandRequest(command='trade', question='again', model='bedrock-haiku')
    agent_runs.record_refusal(guest, request, 'You have used today\'s 5 questions on paid models.')
    return dict(owner=owner, guest=guest, ids=ids)


def test_feedback_only_on_own_answers(seeded):
    owner_run, _, guest_run = seeded['ids'][:3]
    agent_runs.rate(seeded['guest'], guest_run, -1, 'wrong number')
    agent_runs.rate(seeded['guest'], guest_run, 1)  # a second rating replaces the first
    with pytest.raises(HTTPException) as other:
        agent_runs.rate(seeded['guest'], owner_run, 1)
    assert other.value.status_code == 404
    [rated] = [r for r in admin.runs(7) if r['run_id'] == str(guest_run)]
    assert rated['rating'] == 1 and rated['comment'] is None


def test_overview(seeded):
    agent_runs.rate(seeded['guest'], seeded['ids'][2], -1)
    view = admin.overview(7)
    totals = view['totals']
    assert (totals['runs'], totals['questions'], totals['users'], totals['errors']) == (5, 4, 2, 1)
    assert view['feedback'] == {'up': 0, 'down': 1}
    assert view['refusals'][0]['n'] == 1
    assert {t['tool']: t['calls'] for t in view['tools']}['warehouse_coverage'] == 1
    assert view['paid_spend_usd'] == pytest.approx((1000 * 1.0 + 100 * 5.0) / 1e6)
    assert sum(d['runs'] for d in view['daily']) == 5


def test_runs_filters(seeded):
    assert len(admin.runs(7)) == 5
    assert [r['question'] for r in admin.runs(7, q='missing')] == ['Any missing candles?']
    assert [r['status'] for r in admin.runs(7, status='error')] == ['error']
    owned = admin.runs(7, user=seeded['owner'])
    assert len(owned) == 2 and {r['user_label'] for r in owned} == {OWNER}
    assert admin.runs(7, q='100%') == []  # % is literal, not a wildcard
    detail = admin.run(seeded['ids'][1])
    assert detail['steps'][0]['tools'][0]['name'] == 'warehouse_coverage'
    with pytest.raises(HTTPException):
        admin.run(uuid.uuid4())


def test_users(seeded):
    agent_runs.remember_user(GUEST.model_copy(update={'provider': 'github'}))
    agent_runs.remember_user(User(key='a_' + 'b' * 16, anonymous=True))  # never stored
    by_key = {u['user_key']: u for u in admin.users(30)}
    assert by_key[seeded['guest']]['user_label'] == 'guest@example.com'
    assert agent_runs.query('select count(*) as n from meta.app_user')[0]['n'] == 1
    guest, owner = by_key[seeded['guest']], by_key[seeded['owner']]
    assert (guest['runs'], guest['questions'], guest['errors'], guest['paid_runs'], guest['refusals']) == (3, 2, 1, 1, 1)
    assert owner['user_label'] == OWNER and owner['questions'] == 2


def test_models(seeded):
    view = admin.models(7)
    calls = {r['model']: r for r in view['calls']}
    assert calls[GROQ]['calls'] == 2 and calls[GROQ]['after_fallback'] == 1 and calls[GROQ]['label'] == 'GPT-OSS 120B'
    assert calls[HAIKU]['calls'] == 1
    assert view['failures'] == [{'route': 'groq', 'model': GROQ, 'status': 'http_error', 'http_status': '429', 'n': 1}]


def test_system(seeded):
    view = admin.system()
    assert [e['error'] for e in view['recent_errors']] == ['gateway timeout']


def test_trace_view_is_owner_only_and_validates_the_id(monkeypatch):
    from fastapi.testclient import TestClient
    from app import api
    from app.auth import current_user

    calls = []
    monkeypatch.setattr(api, 'gateway', lambda method, path, query=None: calls.append(path) or {'status': 'available'})
    monkeypatch.setenv('AGENT_OWNER_EMAILS', OWNER)
    monkeypatch.setattr(agent_runs, 'query', lambda sql, params=(): [])
    client, tid = TestClient(api.app), 'a' * 32
    try:
        api.app.dependency_overrides[current_user] = lambda: GUEST
        assert client.get(f'/v1/admin/traces/{tid}').status_code == 403
        api.app.dependency_overrides[current_user] = lambda: User(key=user_key(OWNER), email=OWNER)
        assert client.get('/v1/admin/traces/not-a-trace').status_code == 422
        assert client.get(f'/v1/admin/traces/{tid}').json() == {'status': 'available'}
    finally:
        api.app.dependency_overrides.clear()
    assert calls == [['traces', tid]]
