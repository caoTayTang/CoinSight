"""Who is calling: the Cloudflare Access identity when deployed, a single local user in development.

Cloudflare Access signs every request it lets through with a JWT in the Cf-Access-Jwt-Assertion header. The
API verifies it against the team's public keys, with the Access application's AUD tag as audience, and keys
the user by a hash of the email. Set CF_ACCESS_TEAM_DOMAIN (e.g. coinsight.cloudflareaccess.com) and
CF_ACCESS_AUD to require it. Unset, the API is local-only (ports bind to 127.0.0.1) and everyone is 'local'.
"""

import hashlib
import os
from functools import lru_cache

import jwt
from fastapi import HTTPException, Request
from pydantic import BaseModel


class User(BaseModel):
    key: str  # 'local', or 'u_' + 16 hex characters of sha256(email): never the email itself
    email: str | None = None


@lru_cache(maxsize=4)
def signing_keys(team_domain):
    return jwt.PyJWKClient(f'https://{team_domain}/cdn-cgi/access/certs', cache_keys=True, lifespan=3600)


def user_key(email):
    return 'u_' + hashlib.sha256(email.strip().lower().encode()).hexdigest()[:16]


def current_user(request: Request) -> User:
    team, audience = os.getenv('CF_ACCESS_TEAM_DOMAIN'), os.getenv('CF_ACCESS_AUD')
    if not team:
        return User(key='local')
    token = request.headers.get('cf-access-jwt-assertion')
    if not token or not audience:
        raise HTTPException(401, 'Sign in through Cloudflare Access.')
    try:
        key = signing_keys(team).get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=['RS256'], audience=audience, issuer=f'https://{team}')
    except jwt.PyJWTError:
        raise HTTPException(401, 'Invalid or expired Cloudflare Access token.') from None
    email = str(claims.get('email') or '').strip().lower()
    if not email:
        raise HTTPException(401, 'Cloudflare Access token has no email.')
    return User(key=user_key(email), email=email)
