import httpx
import pytest
from warehouse_agents import tools


def patch_http(monkeypatch, respond):
    real = httpx.AsyncClient
    monkeypatch.setattr(
        tools.httpx, 'AsyncClient', lambda **kw: real(transport=httpx.MockTransport(respond), **kw)
    )


def by_component(result):
    return {c['component']: c for c in result['checks']}


@pytest.mark.asyncio
async def test_every_component_reported_from_its_own_signal(monkeypatch):
    def respond(request):
        if request.url.path == '/api/v2/monitor/health':
            return httpx.Response(
                200, json={'metadatabase': {'status': 'healthy'}, 'scheduler': {'status': 'unhealthy'}}
            )
        if request.url.path == '/api/clusters':
            return httpx.Response(
                200, json=[{'name': 'local', 'status': 'ONLINE', 'brokerCount': 1, 'topicCount': 1}]
            )
        return httpx.Response(200, json={})

    def query(sql, params=()):
        if sql == 'select 1':
            return [{'?column?': 1}]
        return [
            {
                'output': 'minute_candles',
                'symbol': 'BTC',
                'latest': '2026-10-21T14:20:00Z',
                'age_seconds': 40,
            },
            {
                'output': 'stream_metrics',
                'symbol': 'BTC',
                'latest': '2026-10-21T13:00:00Z',
                'age_seconds': 4800,
            },
        ]

    patch_http(monkeypatch, respond)
    monkeypatch.setattr(tools, 'query', query)
    checks = by_component(await tools.service_health())
    assert set(checks) == {'warehouse_api', 'forecast', 'traces', 'airflow', 'kafka', 'postgres', 'stream'}
    assert (
        checks['airflow']['status'] == 'degraded' and checks['airflow']['detail']['scheduler'] == 'unhealthy'
    )
    assert checks['kafka']['status'] == 'ok' and checks['postgres']['status'] == 'ok'
    # One stale stream output (80 minutes old) is enough to flag the stream.
    assert checks['stream']['status'] == 'degraded'


@pytest.mark.asyncio
async def test_unreachable_is_not_claimed_as_container_down(monkeypatch):
    def refuse(request):
        raise httpx.ConnectError('private network detail')

    def broken(sql, params=()):
        raise OSError('private connection string')

    patch_http(monkeypatch, refuse)
    monkeypatch.setattr(tools, 'query', broken)
    result = await tools.service_health()
    checks = by_component(result)
    assert all(
        checks[c]['status'] == 'unreachable'
        for c in ('warehouse_api', 'forecast', 'airflow', 'kafka', 'postgres')
    )
    assert checks['stream']['status'] == 'unknown'
    assert 'private' not in str(result) and 'does not prove a container stopped' in result['scope']
    assert result['summary']['unreachable'] == 6


@pytest.mark.asyncio
async def test_http_503_preserves_observed_status(monkeypatch):
    patch_http(monkeypatch, lambda request: httpx.Response(503))
    monkeypatch.setattr(tools, 'query', lambda sql, params=(): [])
    checks = by_component(await tools.service_health())
    assert checks['warehouse_api'] == {
        'component': 'warehouse_api',
        'status': 'degraded',
        'http_status': 503,
        'latency_ms': checks['warehouse_api']['latency_ms'],
    }
    assert checks['stream']['status'] == 'degraded'
