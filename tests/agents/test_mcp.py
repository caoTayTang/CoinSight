import pytest
from mcp import Client
from agents import gateway


@pytest.mark.asyncio
async def test_mcp_returns_structured_a2a_result_and_peer_errors(monkeypatch):
    calls = []

    async def peer(url, payload):
        calls.append((url, payload))
        return dict(
            task_id='forecast-task',
            context_id='context',
            result=dict(status='ready', symbol='ETH'),
        )

    monkeypatch.setattr(gateway, 'call_agent', peer)
    async with Client(gateway.mcp) as client:
        catalog = await client.list_tools()
        assert len(catalog.tools) == 2 and all(t.output_schema for t in catalog.tools)
        result = await client.call_tool('forecast_support', {
            'symbol': 'ETH', 'performance_days': 14, 'market_days': 21,
            'trend_hours': 72, 'cutoff': '2026-01-08T12:00:00Z',
        })
        assert not result.is_error and result.structured_content['result']['symbol'] == 'ETH'
        assert calls[0][1] == dict(
            operation='forecast_support', symbol='ETH', performance_days=14,
            market_days=21, trend_hours=72, cutoff='2026-01-08T12:00:00Z',
        )

        async def broken(*args, **kwargs):
            raise RuntimeError('peer down')

        monkeypatch.setattr(gateway, 'call_agent', broken)
        result = await client.call_tool('forecast_support', {})
        assert result.is_error and not result.structured_content
