from datetime import datetime, timezone
import httpx
import pytest
from agents import market


@pytest.mark.asyncio
async def test_market_uses_only_closed_contiguous_btc_eth_context(monkeypatch):
    real = httpx.AsyncClient
    seen = []
    clock = datetime.now(timezone.utc)

    def response(request):
        seen.append(request)
        if request.url.path.endswith('/time'):
            return httpx.Response(200, json={'serverTime': int(clock.timestamp() * 1000)})
        start = int(request.url.params['startTime'])
        end = int(request.url.params['endTime'])
        assert end < clock.replace(minute=0, second=0, microsecond=0).timestamp() * 1000
        rows = [
            [
                start + i * 3600000,
                '100',
                '101',
                '99',
                '100',
                '1',
                start + (i + 1) * 3600000 - 1,
                '1000',
                10,
                '0',
                '0',
                '0',
            ]
            for i in range(169)
        ]
        return httpx.Response(200, json=rows)

    monkeypatch.setattr(
        market.httpx, 'AsyncClient', lambda **kwargs: real(transport=httpx.MockTransport(response), **kwargs)
    )
    result = await market.load_context()
    assert set(result['contexts']) == {'BTC', 'ETH'} and len(seen) == 3
    assert len(result['snapshot_sha256']) == 64
    assert result['contexts']['BTC']['cutoff'] == result['contexts']['ETH']['cutoff']


@pytest.mark.asyncio
async def test_stale_source_clock_fails_closed(monkeypatch):
    real = httpx.AsyncClient

    def response(request):
        return httpx.Response(200, json={'serverTime': 0})

    monkeypatch.setattr(
        market.httpx, 'AsyncClient', lambda **kwargs: real(transport=httpx.MockTransport(response), **kwargs)
    )
    with pytest.raises(ValueError, match='clock mismatch'):
        await market.load_context()
