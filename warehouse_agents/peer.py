"""A2A peer tracing without mutating a shared HTTP client's headers."""

import os
import httpx
from agents.rpc import call_agent as legacy_call_agent
from warehouse_agents.telemetry import operation, trace_headers, SpanKind


class PropagatingClient:
    def __init__(self, client):
        self.client = client

    def __getattr__(self, key):
        return getattr(self.client, key)

    def kwargs(self, kwargs):
        return dict(kwargs, headers={**kwargs.get('headers', {}), **trace_headers()})

    def build_request(self, method, url, **kwargs):
        return self.client.build_request(method, url, **self.kwargs(kwargs))

    async def get(self, url, **kwargs):
        return await self.client.get(url, **self.kwargs(kwargs))

    async def post(self, url, **kwargs):
        return await self.client.post(url, **self.kwargs(kwargs))

    async def request(self, method, url, **kwargs):
        return await self.client.request(method, url, **self.kwargs(kwargs))


async def call_agent(base_url, payload, *, client=None):
    role = (
        'trade'
        if base_url == os.getenv('ANALYST_AGENT_URL', 'http://127.0.0.1:8021')
        else 'sre'
        if base_url == os.getenv('OPERATIONS_AGENT_URL', 'http://127.0.0.1:8022')
        else 'forecast'
    )
    own = client is None
    client = client or httpx.AsyncClient(timeout=60, follow_redirects=False)
    try:
        with operation(
            'a2a.send', {'rpc.system': 'a2a', 'rpc.method': 'SendMessage', 'a2a.peer': role}, SpanKind.CLIENT
        ) as span:
            reply = await legacy_call_agent(base_url, payload, client=PropagatingClient(client))
            span.set_attribute('a2a.task.id', reply['task_id'])
            return reply
    finally:
        if own:
            await client.aclose()
