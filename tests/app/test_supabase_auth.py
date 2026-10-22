import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException

from app import auth
from app.desk_commands import CommandRequest, payload_for

PROJECT = 'https://project.supabase.co'


class Headers(dict):
    def get(self, key, default=None):
        return super().get(key.lower(), default)


class FakeRequest:
    def __init__(self, headers=None, ip='203.0.113.7'):
        self.headers = Headers({k.lower(): v for k, v in (headers or {}).items()})
        self.client = type('Client', (), {'host': ip})()


@pytest.fixture
def supabase(monkeypatch):
    private = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setenv('SUPABASE_URL', PROJECT)
    monkeypatch.delenv('SUPABASE_PROVIDERS', raising=False)
    monkeypatch.delenv('CF_ACCESS_TEAM_DOMAIN', raising=False)

    class Keys:
        def get_signing_key_from_jwt(self, token):
            return type('Key', (), {'key': private.public_key()})()

    monkeypatch.setattr(auth, 'supabase_keys', lambda url: Keys())

    def bearer(provider='google', **claims):
        base = {
            'aud': 'authenticated',
            'iss': f'{PROJECT}/auth/v1',
            'exp': time.time() + 60,
            'email': 'Alice@Example.com',
            'app_metadata': {'provider': provider},
        }
        return {'Authorization': 'Bearer ' + jwt.encode(base | claims, private, algorithm='ES256')}

    return bearer


def test_google_and_github_sign_ins_are_keyed_by_email(supabase):
    for provider in ('google', 'github'):
        user = auth.current_user(FakeRequest(supabase(provider)))
        assert (user.email, user.provider, user.anonymous) == ('alice@example.com', provider, False)
        assert user.key == auth.user_key('alice@example.com')


@pytest.mark.parametrize(
    'claims',
    [
        {'provider': 'email'},  # unverified email sign-ups must never become an owner's identity
        {'is_anonymous': True},
        {'aud': 'anon'},
        {'iss': 'https://other.supabase.co/auth/v1'},
        {'exp': 1},
        {'email': ''},
    ],
)
def test_untrusted_tokens_are_rejected(supabase, claims):
    provider = claims.pop('provider', 'google')
    with pytest.raises(HTTPException) as refused:
        auth.current_user(FakeRequest(supabase(provider, **claims)))
    assert refused.value.status_code == 401


def test_no_token_is_an_anonymous_visitor_keyed_by_ip(supabase):
    user = auth.current_user(FakeRequest())
    assert user.anonymous and user.email is None and user.key.startswith('a_') and '203' not in user.key
    # Cloudflare's header wins; a spoofed X-Forwarded-For is ignored.
    behind = auth.current_user(FakeRequest({'CF-Connecting-IP': '198.51.100.9', 'X-Forwarded-For': '1.2.3.4'}))
    assert behind.key == auth.anonymous_key('198.51.100.9')


def test_one_ipv6_network_is_one_visitor():
    assert auth.anonymous_key('2001:db8:1:2::1') == auth.anonymous_key('2001:db8:1:2:ffff::9')
    assert auth.anonymous_key('2001:db8:1:2::1') != auth.anonymous_key('2001:db8:1:3::1')


def test_anonymous_visitors_get_no_long_term_memory():
    request = CommandRequest(command='trade', question='q')
    assert 'user' not in payload_for(request, auth.anonymous_key('203.0.113.7'))
    assert payload_for(request, 'u_0123456789abcdef')['user'] == 'u_0123456789abcdef'
