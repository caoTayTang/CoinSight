"""Who is calling: a Supabase sign-in, a Cloudflare Access identity, an anonymous visitor, or 'local'.

Supabase (SUPABASE_URL): the browser signs in with Google or GitHub and sends the Supabase access token as
`Authorization: Bearer`. The API verifies it against the project's public keys (ES256/RS256, no shared secret)
and accepts only the providers in SUPABASE_PROVIDERS, whose emails are verified by Google or GitHub. The app
decides owners by email, so an unverified email sign-up must never count.

Cloudflare Access (CF_ACCESS_TEAM_DOMAIN, CF_ACCESS_AUD): Access signs every request it lets through with a JWT
in the Cf-Access-Jwt-Assertion header, verified against the team's keys with the AUD tag as audience.

Without a token: with Supabase configured, the caller is an anonymous visitor keyed by a hash of their IP
(the /64 network for IPv6, which one household can rotate through), who gets a few free-model questions. With
only Access configured, a token is required. With neither, the API is local-only and everyone is 'local'.
Signed-in users are keyed by a hash of their email.
"""

import hashlib
import ipaddress
import os
from functools import lru_cache

import jwt
from fastapi import HTTPException, Request
from pydantic import BaseModel


class User(BaseModel):
    key: str  # 'local', 'u_' + 16 hex of sha256(email), or 'a_' + 16 hex of sha256(IP network) when anonymous
    email: str | None = None
    provider: str | None = None
    anonymous: bool = False


@lru_cache(maxsize=4)
def signing_keys(team_domain):
    return jwt.PyJWKClient(f'https://{team_domain}/cdn-cgi/access/certs', cache_keys=True, lifespan=3600)


@lru_cache(maxsize=4)
def supabase_keys(project_url):
    return jwt.PyJWKClient(f'{project_url}/auth/v1/.well-known/jwks.json', cache_keys=True, lifespan=3600)


def user_key(email):
    return 'u_' + hashlib.sha256(email.strip().lower().encode()).hexdigest()[:16]


def client_ip(request):
    # Cloudflare sets CF-Connecting-IP and overwrites any value the client sent; X-Forwarded-For is spoofable.
    return request.headers.get('cf-connecting-ip') or (request.client.host if request.client else 'unknown')


def anonymous_key(ip):
    try:
        address = ipaddress.ip_address(ip)
        network = str(ipaddress.ip_network(f'{ip}/64', strict=False)) if address.version == 6 else ip
    except ValueError:
        network = ip
    return 'a_' + hashlib.sha256(network.encode()).hexdigest()[:16]


def supabase_config():
    url = os.getenv('SUPABASE_URL', '').rstrip('/')
    providers = [p.strip() for p in os.getenv('SUPABASE_PROVIDERS', 'google,github').split(',') if p.strip()]
    return dict(url=url, publishable_key=os.getenv('SUPABASE_PUBLISHABLE_KEY', ''), providers=providers)


def supabase_user(token, config):
    try:
        key = supabase_keys(config['url']).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token, key, algorithms=['ES256', 'RS256'], audience='authenticated', issuer=f'{config["url"]}/auth/v1'
        )
    except jwt.PyJWTError:
        raise HTTPException(401, 'Your sign-in has expired. Sign in again.') from None
    provider = (claims.get('app_metadata') or {}).get('provider')
    email = str(claims.get('email') or '').strip().lower()
    if claims.get('is_anonymous') or provider not in config['providers'] or not email:
        raise HTTPException(401, 'Sign in with ' + ' or '.join(p.title() for p in config['providers']) + '.')
    return User(key=user_key(email), email=email, provider=provider)


def access_user(token, team, audience):
    try:
        key = signing_keys(team).get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=['RS256'], audience=audience, issuer=f'https://{team}')
    except jwt.PyJWTError:
        raise HTTPException(401, 'Invalid or expired Cloudflare Access token.') from None
    email = str(claims.get('email') or '').strip().lower()
    if not email:
        raise HTTPException(401, 'Cloudflare Access token has no email.')
    return User(key=user_key(email), email=email, provider='cloudflare-access')


def current_user(request: Request) -> User:
    config = supabase_config()
    team, audience = os.getenv('CF_ACCESS_TEAM_DOMAIN'), os.getenv('CF_ACCESS_AUD')
    scheme, _, bearer = request.headers.get('authorization', '').partition(' ')
    if config['url'] and scheme.lower() == 'bearer' and bearer:
        return supabase_user(bearer, config)
    access_token = request.headers.get('cf-access-jwt-assertion')
    if team and access_token and audience:
        return access_user(access_token, team, audience)
    if config['url']:
        return User(key=anonymous_key(client_ip(request)), anonymous=True)
    if team:
        raise HTTPException(401, 'Sign in through Cloudflare Access.')
    return User(key='local')
