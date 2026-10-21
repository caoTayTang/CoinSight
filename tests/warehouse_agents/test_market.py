from datetime import datetime, timezone
import httpx
import pytest
from warehouse_agents import market


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [None, 'gap', 'count', 'unclosed', 'clock', 'invalid_price'])
async def test_source_validation(monkeypatch, failure):
    now = datetime.now(timezone.utc)
    cutoff = now.replace(minute=0, second=0, microsecond=0)
    end_ms = int(cutoff.timestamp() * 1000)
    start_ms = end_ms - 169 * 3600000
    rows = [
        [
            start_ms + i * 3600000,
            '100',
            '110',
            '90',
            '101',
            '10',
            start_ms + (i + 1) * 3600000 - 1,
            '1000',
            20,
            '0',
            '0',
            '0',
        ]
        for i in range(169)
    ]
    if failure == 'gap':
        rows[10][0] += 1
    if failure == 'count':
        rows.pop()
    if failure == 'unclosed':
        rows[-1][6] += 1
    if failure == 'invalid_price':
        rows[-1][4] = '-1'

    def respond(request):
        if request.url.path.endswith('/time'):
            return httpx.Response(
                200, json={'serverTime': int(now.timestamp() * 1000) + (20000 if failure == 'clock' else 0)}
            )
        return httpx.Response(200, json=rows)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        market.httpx,
        'AsyncClient',
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    if failure:
        with pytest.raises(ValueError):
            await market.closed_window(cutoff=cutoff.isoformat())
    else:
        frame, source = await market.closed_window(cutoff=cutoff.isoformat())
        assert len(frame) == 169 and len(source['snapshot_sha256']) == 64
        with pytest.raises(ValueError, match='Timezone'):
            await market.closed_window(cutoff=cutoff.replace(tzinfo=None).isoformat())
        with pytest.raises(ValueError, match='closed hourly'):
            await market.closed_window(cutoff='2099-01-01T00:00:00Z')


@pytest.mark.asyncio
async def test_market_data_reads_api_view_and_reports_failures(monkeypatch):
    from warehouse_agents import tools

    seen = []

    def respond(request):
        seen.append(request.url.path)
        if 'SOL' in request.url.path:
            return httpx.Response(503)
        return httpx.Response(200, json={'status': 'available', 'data': {'close': 1.0}})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: real(transport=httpx.MockTransport(respond), **kw))
    monkeypatch.setenv('WAREHOUSE_API_URL', 'http://api.test')
    ok = await tools.market_data('live_summary', 'ETH')
    assert ok['status'] == 'available' and ok['data']['data'] == {'close': 1.0}
    failed = await tools.market_data('snapshot', 'SOL')
    assert failed['status'] == 'unavailable' and failed['http_status'] == 503 and 'data' not in failed
    assert seen == ['/v1/assets/ETH/live-summary', '/v1/assets/SOL/snapshot']
