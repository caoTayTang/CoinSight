import os

import pytest

from warehouse_agents import memory

pytestmark = pytest.mark.skipif(
    not os.getenv('MEMORY_TEST_DATABASE_URL'), reason='needs a disposable Postgres for the LangGraph store'
)
ALICE, BOB = 'u_aaaaaaaaaaaaaaaa', 'u_bbbbbbbbbbbbbbbb'


@pytest.fixture(autouse=True)
def database(monkeypatch):
    monkeypatch.setenv('AGENT_STATE_DATABASE_URL', os.environ['MEMORY_TEST_DATABASE_URL'])
    monkeypatch.setattr(memory, '_store', None)


@pytest.mark.asyncio
async def test_memories_are_saved_deduplicated_scoped_and_deleted():
    for user in (ALICE, BOB):
        for item in await memory.list_memories(user, limit=50):
            await memory.delete(user, item['id'])
    first = await memory.save(ALICE, 'Prefers  answers in Vietnamese')
    assert await memory.save(ALICE, 'prefers answers in vietnamese') == first
    assert [m['text'] for m in await memory.list_memories(ALICE)] == ['Prefers answers in Vietnamese']
    assert await memory.list_memories(BOB) == []
    assert await memory.delete(BOB, first) is False
    with pytest.raises(ValueError):
        await memory.save(ALICE, 'my key is gsk_' + 'x' * 30)
    with pytest.raises(ValueError):
        await memory.list_memories('../other')
    assert await memory.delete(ALICE, first) is True and await memory.list_memories(ALICE) == []
