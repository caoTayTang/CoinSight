import os
import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from app import agent_runs, auth
from app.desk_commands import CommandRequest, payload_for


class Headers(dict):
    def get(self, key, default=None):
        return super().get(key.lower(), default)


class FakeRequest:
    def __init__(self, token=None):
        self.headers = Headers({'cf-access-jwt-assertion': token} if token else {})


@pytest.fixture
def access(monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setenv('CF_ACCESS_TEAM_DOMAIN', 'team.cloudflareaccess.com')
    monkeypatch.setenv('CF_ACCESS_AUD', 'aud-tag')

    class Keys:
        def get_signing_key_from_jwt(self, token):
            return type('Key', (), {'key': private.public_key()})()

    monkeypatch.setattr(auth, 'signing_keys', lambda team: Keys())

    def token(**claims):
        base = {'aud': 'aud-tag', 'iss': 'https://team.cloudflareaccess.com', 'exp': time.time() + 60}
        return jwt.encode(base | claims, private, algorithm='RS256')

    return token


def test_local_user_without_cloudflare_access(monkeypatch):
    monkeypatch.delenv('CF_ACCESS_TEAM_DOMAIN', raising=False)
    assert auth.current_user(FakeRequest()).key == 'local'


def test_access_token_verified_and_email_hashed(access):
    user = auth.current_user(FakeRequest(access(email='Alice@Example.com')))
    assert user.email == 'alice@example.com' and user.key == auth.user_key('alice@example.com')
    assert user.key.startswith('u_') and 'alice' not in user.key


@pytest.mark.parametrize('claims', [{'aud': 'other'}, {'iss': 'https://evil.example'}, {'exp': 1}, {}])
def test_bad_or_missing_token_rejected(access, claims):
    token = access(email='a@b.c', **claims) if claims else None
    with pytest.raises(HTTPException) as raised:
        auth.current_user(FakeRequest(token))
    assert raised.value.status_code == 401


def test_gateway_payload_has_user_key_not_thread_or_email():
    thread = uuid.uuid4()
    agent = payload_for(
        CommandRequest(command='trade', question='q', thread_id=thread, model='groq'),
        'u_0123456789abcdef',
        [{'role': 'user', 'text': 'x'}],
    )
    assert agent == {
        'command': 'trade',
        'question': 'q',
        'symbol': 'BTC',
        'user': 'u_0123456789abcdef',
        'history': [{'role': 'user', 'text': 'x'}],
        'model': 'groq',
    }
    assert payload_for(CommandRequest(command='predict'), 'u_0123456789abcdef') == {
        'command': 'predict',
        'question': '',
        'symbol': 'BTC',
    }


@pytest.mark.skipif(
    not os.getenv('AGENT_RUNS_TEST_DATABASE_URL'), reason='needs a disposable Postgres with migration 007'
)
def test_runs_are_logged_and_become_history(monkeypatch):
    monkeypatch.setattr(agent_runs, 'DATABASE_URL', os.environ['AGENT_RUNS_TEST_DATABASE_URL'])
    user, other, thread = 'u_' + uuid.uuid4().hex[:16], 'u_' + uuid.uuid4().hex[:16], uuid.uuid4()
    seen = []

    def fake_command(request, user_key, history):
        seen.append(history)
        if request.question == 'fail':
            raise HTTPException(503, 'down')
        step = {'model': {'model': 'openai/gpt-oss-120b', 'route': 'groq#1'}}
        return {
            'answer': 'answer to ' + request.question,
            'steps': [step],
            'llm_calls': 1,
            'usage': {'inputTokens': 10},
        }

    monkeypatch.setattr(agent_runs, 'command', fake_command)
    first = agent_runs.run(CommandRequest(command='sre', question='one', thread_id=thread), user)
    with pytest.raises(HTTPException):
        agent_runs.run(CommandRequest(command='sre', question='fail', thread_id=thread), user)
    agent_runs.run(CommandRequest(command='trade', question='two', thread_id=thread), user)
    # The failed turn is logged but not replayed as context: the third question sees only the first turn.
    one = [{'role': 'user', 'text': 'one'}, {'role': 'assistant', 'text': 'answer to one'}]
    assert seen == [[], one, one]
    runs = agent_runs.thread(user, thread)
    assert [r['status'] for r in runs] == ['ok', 'error', 'ok'] and runs[0]['models'] == [
        'openai/gpt-oss-120b'
    ]
    assert first['thread_id'] == str(thread) and agent_runs.thread(other, thread) == []
    assert agent_runs.threads(user)[0]['title'] == 'one' and agent_runs.threads(other) == []
    assert agent_runs.delete_thread(other, thread) == 0 and agent_runs.delete_thread(user, thread) == 3
