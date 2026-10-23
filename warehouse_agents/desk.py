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
        forecast = reply.get('forecast_drift') or {}
        if forecast.get('status') == 'available':
            flagged = ', '.join(f"`{v['feature']}` {v['psi']:.2f}" for v in forecast['flagged'][:5]) or 'none'
            forecast_line = (
                f"{len(forecast['flagged'])} of {forecast['features_checked']} input features flagged over "
                f"{forecast['window_feature_rows']} hours ({flagged}). {len(forecast['flagged_long_window'])} slow "
                f"72h/168h features also exceed the threshold, which mostly reflects the current regime; "
                f"{len(forecast['not_covered'])} cross-asset features have no reference yet."
            )
        else:
            forecast_line = 'unavailable: ' + (
                forecast.get('reason') or forecast.get('error_type') or 'unknown'
            )
        live = reply.get('live_performance') or {}
        windows = [w for w in live.get('windows', []) if w['window_label'] == '7d'] or live.get(
            'windows', []
        )[:1]
        if windows:
            w = windows[0]
            live_line = (
                f"{w['window_label']}: n={w['n']}, relative MAE **{w['relative_mae']:.3f}** vs no-change"
                + ('' if live.get('reliable') else ' (fewer than 168 scored hours: not yet reliable)')
            )
        else:
            live_line = f"no scored forecasts yet ({(live.get('ledger') or {}).get('recorded', 0)} recorded)"
        answer = (
            f"**Model health**\n\n**Anomaly model inputs**: {'watch' if reply['drift_watch'] else 'no watch flag'} "
            f"({reply['window_feature_rows']} rows, cutoff `{reply['source']['cutoff']}`)\n{lines}\n\n"
            f"**Forecast model inputs**: {forecast_line}\n\n**Live forecast performance** (prediction ledger): {live_line}\n\n"
            'PSI ≥ 0.25 is a heuristic watch threshold, not proof of model failure.'
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
                price=route.price.model_dump() if route.price else None,
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


async def trace_endpoint(request):
    """One trace's allowlisted span metadata (traces.inspect_trace), for the owners' trace view."""
    from warehouse_agents.traces import inspect_trace

    try:
        return JSONResponse(await inspect_trace(request.path_params['trace_id']))
    except ValueError:
        return JSONResponse({'detail': 'Invalid trace ID'}, status_code=422)
    except Exception:
        return JSONResponse({'status': 'unavailable', 'reason': 'Jaeger could not be reached.'})


async def memories_endpoint(request):
    from warehouse_agents import memory

    try:
        user = user_key(request)
        if request.method == 'DELETE':
            return JSONResponse({'deleted': await memory.delete(user, request.path_params['key'])})
        return JSONResponse({'memories': await memory.list_memories(user, limit=memory.MAX_MEMORIES)})
    except ValueError:
        return JSONResponse({'detail': 'Invalid user'}, status_code=422)
