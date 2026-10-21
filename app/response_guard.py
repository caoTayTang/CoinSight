"""Credential guard for the legacy web entry point and command proxy."""

import json
import os
import re

PATTERN = re.compile(r'(?:sk-or-v1-|gsk_|ABSK)[A-Za-z0-9_+/=.-]{16,}')


def _secrets():
    """Configured key values; an env value may hold a JSON list or comma-separated keys (as the router reads them)."""
    for name, value in os.environ.items():
        if 'KEY' not in name and 'TOKEN' not in name:
            continue
        value = value.strip()
        try:
            items = json.loads(value) if value.startswith('[') else value.split(',')
        except ValueError:
            items = value.strip('[]').split(',')
        yield from (k for k in (str(i).strip().strip('"\'') for i in items) if len(k) > 16)


def reject_credentials(value):
    if PATTERN.search(value):
        raise ValueError('API keys belong in environment configuration, not chat')
    if any(secret in value for secret in _secrets()):
        raise ValueError('API keys belong in environment configuration, not chat')
    return value


def redact_response(value):
    result = PATTERN.sub('[credential redacted]', value)
    for secret in _secrets():
        result = result.replace(secret, '[credential redacted]')
    return result[:30000]
