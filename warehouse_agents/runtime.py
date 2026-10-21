"""Local deployment guardrails: bounded requests, optional bearer auth, bounded task retention."""

import asyncio
import hmac
import os
import time
from collections import OrderedDict
from a2a.server.tasks import InMemoryTaskStore


class BoundedTaskStore(InMemoryTaskStore):
    def __init__(self, max_tasks=256, ttl=3600):
        super().__init__()
        self.max_tasks, self.ttl = max_tasks, ttl
        self.saved = OrderedDict()
        self.lock = asyncio.Lock()

    async def prune(self):
        now = time.monotonic()
        for key, (when, context) in list(self.saved.items()):
            if now - when > self.ttl or len(self.saved) > self.max_tasks:
                await super().delete(key, context)
                del self.saved[key]

    async def save(self, task, context):
        async with self.lock:
            await super().save(task, context)
            self.saved[task.id] = (time.monotonic(), context)
            self.saved.move_to_end(task.id)
            await self.prune()

    async def get(self, task_id, context):
        async with self.lock:
            await self.prune()
            return await super().get(task_id, context)

    async def list(self, params, context):
        async with self.lock:
            await self.prune()
            return await super().list(params, context)

    async def delete(self, task_id, context):
        async with self.lock:
            await super().delete(task_id, context)
            self.saved.pop(task_id, None)


class LocalGuard:
    def __init__(self, app, token=None, max_bytes=32768, requests_per_minute=60):
        self.app = app
        self.token = os.getenv('WAREHOUSE_AGENT_TOKEN', '') if token is None else token
        self.max_bytes, self.rate = max_bytes, requests_per_minute
        self.requests = []

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['path'] == '/health':
            return await self.app(scope, receive, send)
        headers = dict(scope['headers'])

        async def reject(status, text):
            await send(
                {
                    'type': 'http.response.start',
                    'status': status,
                    'headers': [(b'content-type', b'text/plain')],
                }
            )
            await send({'type': 'http.response.body', 'body': text.encode()})

        if self.token and not hmac.compare_digest(
            headers.get(b'authorization', b''), ('Bearer ' + self.token).encode()
        ):
            return await reject(401, 'Bearer authentication required')
        if scope['method'] == 'POST':
            now = time.monotonic()
            self.requests = [t for t in self.requests if now - t < 60]
            if len(self.requests) >= self.rate:
                return await reject(429, 'Request budget exceeded')
            self.requests.append(now)
            # Buffer a strictly bounded body before parsing JSON/SDK requests.
            body = bytearray()
            try:
                async with asyncio.timeout(10):
                    while True:
                        message = await receive()
                        if message['type'] == 'http.disconnect':
                            return
                        chunk = message.get('body', b'')
                        if len(body) + len(chunk) > self.max_bytes:
                            return await reject(413, 'Request too large')
                        body.extend(chunk)
                        if not message.get('more_body', False):
                            break
            except TimeoutError:
                return await reject(408, 'Request body timeout')
            delivered = False

            async def bounded_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
                return await receive()

            return await self.app(scope, bounded_receive, send)
        return await self.app(scope, receive, send)
