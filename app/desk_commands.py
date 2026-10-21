"""Same-origin web command proxy; provider/service secrets stay on the server."""

import json
import os
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
from typing import Literal
from urllib.parse import quote, urlencode
from uuid import UUID
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

try:
    from .response_guard import reject_credentials
except ImportError:
    from response_guard import reject_credentials


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    command: Literal['trade', 'sre', 'predict', 'anomaly', 'drift']
    question: str = Field(default='', max_length=2000)
    symbol: Literal['BTC', 'ETH', 'SOL'] = 'BTC'
    # Conversation the question belongs to (earlier turns become context), and an optional router route
    # the user picked in the model picker; None means automatic routing.
    thread_id: UUID | None = None
    model: str | None = Field(default=None, pattern=r'^[a-zA-Z0-9_-]{1,64}$')

    @model_validator(mode='after')
    def scope(self):
        reject_credentials(self.question)
        if self.command in ('trade', 'sre') and not self.question.strip():
            raise ValueError('Add a question after @trade or @sre')
        if self.command in ('predict', 'anomaly', 'drift') and (self.symbol != 'BTC' or self.question):
            raise ValueError('Direct ML commands support BTC only and no question text')
        return self


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


DESK_URL = 'http://host.docker.internal:8020/desk/command'


def _command(payload: dict):
    url = os.getenv('WAREHOUSE_DESK_URL', DESK_URL)
    headers = {'Content-Type': 'application/json'}
    token = os.getenv('WAREHOUSE_AGENT_TOKEN')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    TraceContextTextMapPropagator().inject(headers)
    req = Request(url, data=json.dumps(payload).encode(), headers=headers, method='POST')
    try:
        with build_opener(NoRedirect()).open(req, timeout=280) as response:
            body = response.read(262145)
            if len(body) > 262144:
                raise ValueError('Command response too large')
            result = json.loads(body)
            if not isinstance(result, dict) or not isinstance(result.get('answer'), str):
                raise ValueError('Invalid command response')
            return result
    except HTTPError as exc:
        if exc.code == 429:
            raise HTTPException(429, 'Command service request budget reached; retry later.') from None
        if exc.code == 422:
            raise HTTPException(
                422, 'Invalid command. ML tools support BTC only; agents require a question.'
            ) from None
        raise HTTPException(503, 'Agent/tool service unavailable. Check extension service logs.') from None
    except Exception:
        raise HTTPException(503, 'Agent/tool service unavailable. No result was invented.') from None


try:
    from .telemetry import traced, operation, current_trace_id
except ImportError:
    from telemetry import traced, operation, current_trace_id


def payload_for(request: CommandRequest, user_key='local', history=()):
    """What the extension gateway receives: never the thread ID or the user's email, only a hashed user key."""
    payload = request.model_dump(include={'command', 'question', 'symbol'})
    if request.command in ('trade', 'sre'):
        payload.update(user=user_key, history=list(history))
        if request.model:
            payload['model'] = request.model
    return payload


@traced('desk.command')
def command(request: CommandRequest, user_key='local', history=()):
    with operation('desk.gateway', {'desk.command': request.command}) as span:
        result = _command(payload_for(request, user_key, history))
        tid = current_trace_id()
        if tid:
            result['api_trace_id'] = tid
            if result.get('trace_id'):
                span.set_attribute('gateway.trace.id', result['trace_id'])
        return result


def gateway(method, path, query=None):
    """GET/DELETE on the extension gateway's desk endpoints (models, memories), with the server token."""
    base = os.getenv('WAREHOUSE_DESK_URL', DESK_URL).rsplit('/desk/command', 1)[0]
    url = (
        base
        + '/desk/'
        + '/'.join(quote(p, safe='') for p in path)
        + ('?' + urlencode(query) if query else '')
    )
    headers = (
        {'Authorization': 'Bearer ' + os.environ['WAREHOUSE_AGENT_TOKEN']}
        if os.getenv('WAREHOUSE_AGENT_TOKEN')
        else {}
    )
    try:
        with build_opener(NoRedirect()).open(
            Request(url, headers=headers, method=method), timeout=15
        ) as response:
            return json.loads(response.read(262145))
    except Exception:
        raise HTTPException(503, 'Agent service unavailable.') from None
