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
            result=dict(predicted_log_return=0.001, anomaly_task_id='peer-task'),
        )

    monkeypatch.setattr(gateway, 'call_agent', peer)
    async with Client(gateway.mcp) as client:
        catalog = await client.list_tools()
        assert len(catalog.tools) == 2 and all(t.output_schema for t in catalog.tools)
        result = await client.call_tool('predict_hourly', {'cutoff': '2026-01-08T00:00:00Z'})
        assert not result.is_error and result.structured_content['result']['anomaly_task_id'] == 'peer-task'
        assert calls[0][1] == dict(operation='predict_hourly', cutoff='2026-01-08T00:00:00Z')

        async def broken(*args, **kwargs):
            raise RuntimeError('peer down')

        monkeypatch.setattr(gateway, 'call_agent', broken)
        result = await client.call_tool('predict_hourly', {})
        assert result.is_error and not result.structured_content
