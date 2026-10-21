"""Validated HTTP bridge for the web Desk; shares the existing read-only tools/agents."""

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Literal
import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.responses import JSONResponse
from warehouse_agents.peer import call_agent
from warehouse_agents import tools
from warehouse_agents.telemetry import traced, trace_id
from warehouse_agents.guardrails import reject_credentials, guard_answer
from warehouse_agents.server import Turn


class DeskRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    command: Literal['trade', 'sre', 'predict', 'anomaly', 'drift']
    question: str = Field(default='', max_length=2000)
    symbol: Literal['BTC', 'ETH', 'SOL'] = 'BTC'
    history: list[Turn] = Field(default_factory=list, max_length=12)
    model: str | None = Field(default=None, pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    user: str | None = Field(default=None, pattern=r'^(local|u_[a-f0-9]{16})$')

    @model_validator(mode='after')
    def scope(self):
        reject_credentials(self.question)
        if self.command in ('trade', 'sre') and not self.question.strip():
            raise ValueError('Agent question required')
        if self.command in ('predict', 'anomaly', 'drift') and self.symbol != 'BTC':
            raise ValueError('This model tool supports BTC only; specify BTC explicitly')
        if self.command in ('predict', 'anomaly', 'drift') and self.question:
            raise ValueError('Direct model tools accept only the asset, not a free-form question')
        return self


@traced('desk.dispatch')
async def execute(request):
    if request.command in ('trade', 'sre'):
        base = (
            os.getenv('ANALYST_AGENT_URL', 'http://127.0.0.1:8021')
            if request.command == 'trade'
            else os.getenv('OPERATIONS_AGENT_URL', 'http://127.0.0.1:8022')
        )
        async with httpx.AsyncClient(
            timeout=265, follow_redirects=False, headers=tools.peer_headers()
        ) as client:
            payload = {'question': request.question, 'symbol': request.symbol}
            payload.update(request.model_dump(include={'history', 'model', 'user'}, exclude_none=True))
            reply = await call_agent(base, payload, client=client)
        result = reply['result']
        return {
            'command': request.command,
            'answer': result['answer'],
            'task_id': reply['task_id'],
            'routing': result.get('routing', []),
            'steps': result.get('steps', []),
            'guardrails': result.get('guardrails'),
            'evidence': result.get('evidence', []),
            'trace_id': trace_id(),
            'usage': result.get('usage', {}),
            'llm_calls': result.get('llm_calls', 0),
        }
    if request.command == 'predict':
        reply = await tools.predict_hourly()
        r = reply['result']
        answer = (
            f"**BTC hourly forecast**\n\nCutoff: `{r['cutoff']}`\n\n"
            f"- Predicted log return: **{r['predicted_log_return']:.8f}**\n"
            f"- Reference close: **{r['reference_close_usdt']:.2f} USDT**; predicted close: **{r['predicted_close_usdt']:.2f} USDT**\n"
            f"- Target: `{r['target_open']}` → `{r['target_close']}`; generated: `{r['generated_at']}`.\n\n"
            f"Timing: `{r['timing']}`. Research forecast, not a probability or trading instruction."
        )
    elif request.command == 'anomaly':
        reply = await tools.detect_market_anomaly()
        r = reply['trained']
        answer = (
            f"**BTC market anomaly: {'FLAGGED' if r['is_anomaly'] else 'not flagged'}**\n\n"
            f"Cutoff: `{r['cutoff']}`\n\n- Isolation Forest score: **{r['score']:.6f}**; threshold: **{r['threshold']:.6f}**.\n"
            f"- MAD baseline: **{'flagged' if reply['mad_baseline']['is_anomaly'] else 'not flagged'}**.\n\n"
            "Unusualness of a closed candle; not a crash probability or proof of bad data. No labeled accuracy is established."
        )
    else:
        reply = await tools.model_health()
        top = reply['data_drift'][:3]
        lines = '\n'.join(f"- `{v['feature']}`: PSI **{v['psi']:.4f}**" for v in top)
        answer = (
            f"**BTC feature drift: {'watch' if reply['drift_watch'] else 'no watch flag'}**\n\n"
            f"Cutoff: `{reply['source']['cutoff']}`; feature rows: **{reply['window_feature_rows']}**.\n\n{lines}\n\n"
            "PSI ≥ 0.25 is a heuristic watch threshold, not proof of forecast failure. Current MAE is unavailable without a prospective ledger."
        )
    answer, policy = guard_answer(answer, reply)
    return {
        'command': request.command,
        'answer': answer,
        'guardrails': policy,
        'evidence': reply,
        'trace_id': trace_id(),
        'routing': [],
        'llm_calls': 0,
    }


async def endpoint(request):
    try:
        parsed = DeskRequest.model_validate(await request.json())
    except Exception:
        return JSONResponse(
            {
                'detail': 'Invalid command/input. Use @trade or @sre with a question; direct ML tools support BTC only.'
            },
            status_code=422,
        )
    try:
        async with asyncio.timeout(270):
            return JSONResponse(await execute(parsed))
    except Exception as exc:
        return JSONResponse(
            {'detail': f'Command unavailable ({type(exc).__name__}); no fallback result was invented.'},
            status_code=503,
        )


MODEL_CARD = Path(__file__).parent / 'model_card.json'


def models():
    """Routes the user can pick, with whether their keys are configured and eval results if measured."""
    from warehouse_agents.guardrails import split_keys
    from warehouse_agents.router import Router

    card = json.loads(MODEL_CARD.read_text()) if MODEL_CARD.exists() else {}
    routes = []
    for route in Router().config.routes:
        keys = split_keys(os.getenv(route.api_key_env, '')) if route.api_key_env else [None]
        routes.append(
            dict(
                name=route.name,
                label=route.label or route.model,
                provider=route.provider,
                model=route.model,
                tier=route.tier,
                keys=len(keys),
                available=bool(keys),
                eval=card.get('models', {}).get(route.model),
            )
        )
    return {'routes': routes, 'eval_source': card.get('source')}


async def models_endpoint(_request):
    return JSONResponse(models())


def user_key(request):
    key = request.query_params.get('user', '')
    if not re.fullmatch(r'local|u_[a-f0-9]{16}', key):
        raise ValueError('Invalid user key')
    return key


async def memories_endpoint(request):
    from warehouse_agents import memory

    try:
        user = user_key(request)
        if request.method == 'DELETE':
            return JSONResponse({'deleted': await memory.delete(user, request.path_params['key'])})
        return JSONResponse({'memories': await memory.list_memories(user, limit=memory.MAX_MEMORIES)})
    except ValueError:
        return JSONResponse({'detail': 'Invalid user'}, status_code=422)
