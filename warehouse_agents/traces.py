"""Bounded read-only Jaeger v3 queries. Expose timing/error metadata, never logs or bodies."""

import json
import os
import re
from datetime import datetime, timedelta, timezone
import httpx
from warehouse_agents.guardrails import redact

SERVICES = (
    'coinsight-api',
    'coinsight-producer',
    'coinsight-spark',
    'coinsight-trade',
    'coinsight-sre',
    'coinsight-agent-gateway',
)
SAFE_ATTRIBUTES = {
    'error.type',
    'http.response.status_code',
    'http.status_code',
    'gen_ai.provider.name',
    'gen_ai.request.model',
    'gen_ai.tool.name',
    'gen_ai.usage.input_tokens',
    'gen_ai.usage.output_tokens',
    'a2a.task.id',
    'desk.command',
    'error',
}


def attributes(items):
    result = {}
    for item in items or []:
        value = item.get('value', {})
        for key in ('stringValue', 'intValue', 'doubleValue', 'boolValue'):
            if key in value:
                result[item.get('key')] = value[key]
                break
    return result


def span_rows(documents):
    rows = []
    for document in documents:
        if 'error' in document:
            raise ValueError('Jaeger stream returned an error')
        for resource in document.get('result', document).get('resourceSpans', []):
            service = attributes(resource.get('resource', {}).get('attributes')).get(
                'service.name', 'unknown'
            )
            if service not in SERVICES:
                continue
            for scope in resource.get('scopeSpans', []):
                for span in scope.get('spans', []):
                    trace_id = span.get('traceId', '').lower()
                    if not re.fullmatch(r'[a-f0-9]{32}', trace_id):
                        raise ValueError('Invalid trace ID from Jaeger')
                    start, end = int(span['startTimeUnixNano']), int(span['endTimeUnixNano'])
                    if end < start:
                        raise ValueError('Invalid span timing')
                    values = attributes(span.get('attributes'))
                    safe = {
                        k: redact(str(v))[:160] if isinstance(v, str) else v
                        for k, v in values.items()
                        if k in SAFE_ATTRIBUTES
                    }
                    http_code = values.get('http.response.status_code', values.get('http.status_code', 0))
                    error = (
                        span.get('status', {}).get('code') in (2, 'STATUS_CODE_ERROR')
                        or values.get('error') is True
                    )
                    try:
                        error = error or int(http_code) >= 400
                    except (ValueError, TypeError):
                        pass
                    rows.append(
                        dict(
                            trace_id=trace_id,
                            span_id=span.get('spanId', '')[:16],
                            parent_span_id=span.get('parentSpanId', '')[:16],
                            service=service,
                            operation=redact(str(span.get('name', 'unknown')))[:160],
                            start_ns=start,
                            duration_ms=round((end - start) / 1e6, 3),
                            error=bool(error),
                            attributes=safe,
                        )
                    )
                    if len(rows) > 2000:
                        raise ValueError('Trace response exceeds span budget')
    return rows


async def query(path, params=None):
    base = os.getenv('JAEGER_URL', 'http://127.0.0.1:16686').rstrip('/')
    async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
        async with client.stream('GET', base + path, params=params) as response:
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 1048576:
                    raise ValueError('Jaeger response exceeds 1 MiB')
            # Jaeger v3 reports an empty search as a JSON 404, unlike an absent API route.
            if response.status_code == 404:
                try:
                    if json.loads(body).get('error', {}).get('message') == 'No traces found':
                        return []
                except (ValueError, AttributeError):
                    pass
            response.raise_for_status()
    # The v3 gateway emits newline-delimited JSON stream envelopes.
    return span_rows([json.loads(line) for line in body.decode().splitlines() if line.strip()])


def summary(rows):
    start = min(r['start_ns'] for r in rows)
    end = max(r['start_ns'] + round(r['duration_ms'] * 1e6) for r in rows)
    return dict(
        trace_id=rows[0]['trace_id'],
        started_at=datetime.fromtimestamp(start / 1e9, timezone.utc).isoformat(),
        duration_ms=round((end - start) / 1e6, 3),
        span_count=len(rows),
        error_spans=sum(r['error'] for r in rows),
        services=sorted({r['service'] for r in rows}),
        scope='Observed spans from allowlisted services; sampling/retention may omit spans. Error spans do not prove root cause.',
    )


async def search_traces(service='coinsight-api', lookback_minutes=30, limit=5):
    if (
        service not in SERVICES
        or type(lookback_minutes) is not int
        or not 1 <= lookback_minutes <= 1440
        or type(limit) is not int
        or not 1 <= limit <= 5
    ):
        raise ValueError('Unsupported service or trace search bounds')
    now = datetime.now(timezone.utc)
    rows = await query(
        '/api/v3/traces',
        {
            'query.service_name': service,
            'query.start_time_min': (now - timedelta(minutes=lookback_minutes)).isoformat(),
            'query.start_time_max': now.isoformat(),
            'query.num_traces': limit,
        },
    )
    grouped = {}
    for row in rows:
        grouped.setdefault(row['trace_id'], []).append(row)
    traces = sorted((summary(v) for v in grouped.values()), key=lambda t: t['started_at'], reverse=True)[
        :limit
    ]
    return dict(
        status='available',
        service=service,
        lookback_minutes=lookback_minutes,
        traces=traces,
        scope='Bounded recent trace search, not service health. Empty results can mean no traffic, sampling or retention.',
    )


async def inspect_trace(trace_id):
    if not isinstance(trace_id, str) or not re.fullmatch(r'[a-fA-F0-9]{32}', trace_id):
        raise ValueError('Use a 32-character hex trace ID')
    trace_id = trace_id.lower()
    rows = [r for r in await query('/api/v3/traces/' + trace_id) if r['trace_id'] == trace_id]
    if not rows:
        return dict(
            status='unavailable',
            reason='No allowlisted spans found; trace may be absent, unsampled or expired.',
        )
    result = summary(rows)
    start = min(r['start_ns'] for r in rows)
    rows.sort(key=lambda r: r['start_ns'])
    selected = rows[:64]
    # Keep errors visible even when a large trace must be truncated.
    if len(rows) > 64:
        selected = sorted(sorted(rows, key=lambda r: not r['error'])[:64], key=lambda r: r['start_ns'])
    spans = [
        {k: v for k, v in row.items() if k not in ('trace_id', 'start_ns')}
        | {'offset_ms': round((row['start_ns'] - start) / 1e6, 3)}
        for row in selected
    ]
    return dict(
        status='available',
        **result,
        spans=spans,
        spans_truncated=len(rows) > 64,
        content_policy='Allowlisted metadata only; span logs, events, prompts, bodies, SQL and exception messages omitted.',
    )
