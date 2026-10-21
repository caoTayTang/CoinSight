"""Deterministic evidence and credential guards; no claim to prove arbitrary LLM prose true."""

import json
import os
import re

SECRET = re.compile(r'(?:sk-or-v1-|gsk_|ABSK)[A-Za-z0-9_+/=.-]{16,}')


def split_keys(value):
    """One or more keys from an env value: a JSON list ["k1","k2"], comma-separated k1,k2, or a single key."""
    value = (value or '').strip()
    if value.startswith('['):
        try:
            items = json.loads(value)
        except ValueError:
            items = value.strip('[]').split(',')
    else:
        items = value.split(',')
    return [k for k in (str(i).strip().strip('"\'') for i in items) if k]


def configured_secrets():
    for name, value in os.environ.items():
        if 'KEY' in name or 'TOKEN' in name:
            yield from (k for k in split_keys(value) if len(k) > 16)


def reject_credentials(text):
    if SECRET.search(text):
        raise ValueError('Credential-like input rejected; store API keys in environment configuration')
    if any(secret in text for secret in configured_secrets()):
        raise ValueError('Credential-like input rejected; store API keys in environment configuration')


def redact(text):
    result = SECRET.sub('[credential redacted]', text)
    for secret in configured_secrets():
        result = result.replace(secret, '[credential redacted]')
    return result


def statuses(value, depth=0):
    if depth > 8:
        return []
    if isinstance(value, list):
        return [s for v in value[:32] for s in statuses(v, depth + 1)]
    if not isinstance(value, dict):
        return []
    # Delegation wrappers must not hide unavailable leaf observations behind status=available.
    children = []
    for key in ('evidence', 'result'):
        if key in value:
            children.extend(statuses(value[key], depth + 1))
    if children:
        return children
    status = value.get('status')
    return [status] if status in ('available', 'unavailable', 'truncated') else []


def guard_answer(answer, evidence, language='en'):
    observed = statuses(evidence)
    available = observed.count('available')
    missing = len(observed) - available
    state = (
        'partial'
        if available and missing
        else 'available'
        if available
        else 'unavailable'
        if missing
        else 'none'
    )
    warnings = []
    if state == 'unavailable':
        answer = (
            'Chưa thể xác minh kết luận: các công cụ được gọi đều không trả được bằng chứng sử dụng được. '
            'Hãy kiểm tra phần Tool evidence và kết nối nguồn trước khi kết luận dữ liệu hoặc hệ thống đang khỏe.'
            if language == 'vi'
            else 'The requested conclusion could not be verified: all called tools returned unavailable or truncated evidence. '
            'Inspect Tool evidence and source connectivity before making a data or health conclusion.'
        )
        warnings.append('All called tools lacked usable evidence; the model conclusion was replaced.')
    elif state == 'partial':
        warnings.append(
            'Some tool attempts failed or were unavailable. Review the trace; conclusions only cover returned observations.'
        )
    elif state == 'none':
        warnings.append(
            'No tool evidence was collected. Treat this as an explanation, not a verified market or system observation.'
        )
    cleaned = redact(answer)
    if cleaned != answer:
        warnings.append('Credential-like content was redacted from the response.')
    if len(cleaned) > 30000:
        cleaned = cleaned[:30000] + '\n\n[Response truncated]'
        warnings.append('Response exceeded the 30,000-character limit.')
    return cleaned, {
        'scope': 'read_only',
        'evidence_status': state,
        'warnings': warnings,
        'numeric_charts': 'tool_evidence_only',
        'diagrams': 'schematic_not_measured',
        'limits': 'These guards do not certify every claim, defeat every prompt injection, or validate profitability.',
    }
