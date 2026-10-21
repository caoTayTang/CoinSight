import pytest
import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from warehouse_agents.runtime import LocalGuard
from warehouse_agents.server import Request


def test_request_rejects_extra_and_oversized_question():
    from pydantic import ValidationError

    for value in (
        {'question': 'x', 'sql': 'drop'},
        {'question': 'x' * 3001},
        {'question': 'x', 'symbol': 'INVALID'},
    ):
        with pytest.raises(ValidationError):
            Request.model_validate(value)


@pytest.mark.asyncio
async def test_auth_body_limit_and_rate():
    async def endpoint(request):
        return JSONResponse({'ok': True})

    app = LocalGuard(
        Starlette(routes=[Route('/', endpoint, methods=['POST']), Route('/health', endpoint)]),
        token='test-token',
        max_bytes=20,
        requests_per_minute=2,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.get('/health')).status_code == 200
        assert (await client.post('/', json={})).status_code == 401
        headers = {'Authorization': 'Bearer test-token'}
        assert (await client.post('/', content='x' * 21, headers=headers)).status_code == 413
        assert (await client.post('/', content='{}', headers=headers)).status_code == 200
        assert (await client.post('/', content='{}', headers=headers)).status_code == 429


@pytest.mark.asyncio
async def test_task_store_bounded_and_expiring():
    import time
    from a2a.helpers import new_data_message, new_task_from_user_message
    from a2a.server.context import ServerCallContext
    from a2a.types import Role
    from warehouse_agents.runtime import BoundedTaskStore

    store = BoundedTaskStore(max_tasks=1, ttl=3600)
    context = ServerCallContext()
    first = new_task_from_user_message(new_data_message({'a': 1}, role=Role.ROLE_USER))
    second = new_task_from_user_message(new_data_message({'a': 2}, role=Role.ROLE_USER))
    await store.save(first, context)
    await store.save(second, context)
    assert await store.get(first.id, context) is None
    assert (await store.get(second.id, context)).id == second.id
    store.saved[second.id] = (time.monotonic() - 7200, context)
    assert await store.get(second.id, context) is None
