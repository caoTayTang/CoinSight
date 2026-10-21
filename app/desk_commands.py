"""Same-origin web command proxy; provider/service secrets stay on the server."""

import json
import os
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
from typing import Literal
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


def _command(request: CommandRequest):
    url = os.getenv('WAREHOUSE_DESK_URL', 'http://host.docker.internal:8020/desk/command')
    headers = {'Content-Type': 'application/json'}
    token = os.getenv('WAREHOUSE_AGENT_TOKEN')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    TraceContextTextMapPropagator().inject(headers)
    req = Request(url, data=json.dumps(request.model_dump()).encode(), headers=headers, method='POST')
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


@traced('desk.command')
def command(request: CommandRequest):
    with operation('desk.gateway', {'desk.command': request.command}) as span:
        result = _command(request)
        tid = current_trace_id()
        if tid:
            result['api_trace_id'] = tid
            if result.get('trace_id'):
                span.set_attribute('gateway.trace.id', result['trace_id'])
        return result
