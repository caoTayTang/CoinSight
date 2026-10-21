"""Real HTTP/A2A transport integration with explicitly scripted, offline LLM responses."""

import asyncio
from contextlib import asynccontextmanager
import socket
import httpx
import pytest
import uvicorn
from agents.rpc import call_agent
from warehouse_agents.graph import Reasoner
from warehouse_agents.server import create_app
from warehouse_agents.runtime import LocalGuard


class ScriptedLLM:
    def __init__(self, name, arguments):
        self.name, self.arguments, self.calls = name, arguments, 0

    async def converse(self, **kwargs):
        self.calls += 1
        content = (
            [{'toolUse': {'toolUseId': 'test-use', 'name': self.name, 'input': self.arguments}}]
            if self.calls == 1
            else [{'text': 'Offline test: evidence collected.'}]
        )
        return {'output': {'message': {'role': 'assistant', 'content': content}}}


@asynccontextmanager
async def serve(app):
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level='warning', lifespan='off'))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if task.done():
                    await task
                await asyncio.sleep(0.01)
        yield f'http://127.0.0.1:{port}'
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 10)
        sock.close()


@pytest.mark.asyncio
async def test_real_a2a_delegation_and_auth(monkeypatch):
    monkeypatch.setenv('WAREHOUSE_AGENT_TOKEN', 'integration-test-token')

    async def evidence():
        return {'status': 'unavailable', 'observed_at': 'test-timestamp', 'reason': 'Scripted test fixture'}

    ops = Reasoner('operations', ScriptedLLM('warehouse_status', {}), {'warehouse_status': evidence})
    async with serve(LocalGuard(create_app('operations', ops))) as ops_url:
        monkeypatch.setenv('OPERATIONS_AGENT_URL', ops_url)
        analyst = Reasoner('analyst', ScriptedLLM('investigate_warehouse', {'question': 'Inspect fixture'}))
        async with serve(LocalGuard(create_app('analyst', analyst))) as analyst_url:
            async with httpx.AsyncClient(
                timeout=15, headers={'Authorization': 'Bearer integration-test-token'}
            ) as client:
                reply = await call_agent(analyst_url, {'question': 'Inspect fixture'}, client=client)
                assert reply['result']['role'] == 'analyst'
                delegated = reply['result']['evidence'][0]['result']
                assert delegated['task_id'] != reply['task_id']
                assert delegated['result']['role'] == 'operations'
                assert delegated['result']['evidence'][0]['result']['status'] == 'unavailable'
                with pytest.raises(RuntimeError, match='ValidationError'):
                    await call_agent(analyst_url, {'question': 'x', 'sql': 'drop'}, client=client)
            async with httpx.AsyncClient() as client:
                assert (await client.get(analyst_url + '/.well-known/agent-card.json')).status_code == 401
