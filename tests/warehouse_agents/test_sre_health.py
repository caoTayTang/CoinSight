import httpx
import pytest
from warehouse_agents import tools


@pytest.mark.asyncio
async def test_unreachable_is_not_claimed_as_container_down(monkeypatch):
    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            raise httpx.ConnectError('private network detail')

    monkeypatch.setattr(tools.httpx, 'AsyncClient', Client)
    result = await tools.service_health()
    assert all(r['status'] == 'unreachable' for r in result['checks'])
    assert 'private network' not in str(result)
    assert 'HTTP reachability only' in result['scope']
    assert not any('container' in r for r in result['checks'])


@pytest.mark.asyncio
async def test_http_503_preserves_observed_status(monkeypatch):
    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            return httpx.Response(503, request=httpx.Request('GET', url))

    monkeypatch.setattr(tools.httpx, 'AsyncClient', Client)
    result = await tools.service_health()
    assert all(r['status'] == 'http_error' and r['http_status'] == 503 for r in result['checks'])
