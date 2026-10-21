"""Tiered provider/model/key routing with failover. No tool is executed by this router.

Routes are tried tier by tier (lowest first). A route whose key variable holds several keys
(GROQ_API_KEY=["k1","k2"] or k1,k2) becomes one slot per key: groq#1, groq#2. Within a tier, `round_robin`
rotates the starting slot per call to spread load; `priority` keeps file order. A failed slot cools down for
`cooldown_seconds`, or for as long as the provider's Retry-After asks (capped), before it is tried again.
"""

import asyncio
import json
import os
import time
from pathlib import Path
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal
from warehouse_agents.guardrails import split_keys
from warehouse_agents.telemetry import operation, SpanKind, Status, StatusCode


class Route(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    provider: Literal['bedrock', 'groq', 'openrouter', 'openai_compatible']
    model: str = Field(min_length=1, max_length=250)
    api_key_env: str | None = Field(default=None, pattern=r'^[A-Z][A-Z0-9_]*$')
    region: str = Field(default='us-east-1', pattern=r'^[a-z]{2}(?:-[a-z]+)+-\d$')
    # Lower tiers are tried first; a higher tier is only reached when every route below it fails or cools down.
    tier: int = Field(default=0, ge=0, le=9)
    # Name shown in the model picker.
    label: str | None = Field(default=None, max_length=60)
    # Self-hosted servers (vLLM, llama.cpp, Ollama) expose /v1/chat/completions; a key is optional.
    base_url: str | None = Field(
        default=None, pattern=r'^https?://[A-Za-z0-9.\-]+(?::\d+)?(?:/[A-Za-z0-9._\-/]*)?$'
    )

    @model_validator(mode='after')
    def base_url_only_for_self_hosted(self):
        if (self.provider == 'openai_compatible') != (self.base_url is not None):
            raise ValueError('base_url is required for openai_compatible and not allowed otherwise')
        return self


class RouterConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    strategy: Literal['priority', 'round_robin'] = 'priority'
    routes: list[Route] = Field(min_length=1, max_length=12)
    timeout_seconds: float = Field(default=15, ge=1, le=120)
    total_timeout_seconds: float = Field(default=45, ge=1, le=300)
    cooldown_seconds: float = Field(default=30, ge=1, le=300)


MAX_COOLDOWN_SECONDS = 3600
REASONING_LIMIT = 4000


def retry_after_seconds(value):
    """Seconds from a Retry-After header (delta-seconds form only); 0 when absent or unparseable."""
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


class RouterUnavailable(RuntimeError):
    def __init__(self, attempts):
        self.attempts = attempts
        super().__init__('All configured LLM routes unavailable; inspect sanitized routing attempts.')


def chat_request(request, model):
    """Converse text/tool history -> OpenAI-compatible chat, preserving every tool-call ID."""
    messages = []
    system = '\n'.join(p['text'] for p in request.get('system', []))
    if system:
        messages.append({'role': 'system', 'content': system})
    for message in request['messages']:
        text, calls, results = [], [], []
        for part in message['content']:
            if 'text' in part:
                text.append(part['text'])
            elif 'toolUse' in part:
                u = part['toolUse']
                calls.append(
                    {
                        'id': u['toolUseId'],
                        'type': 'function',
                        'function': {'name': u['name'], 'arguments': json.dumps(u['input'], allow_nan=False)},
                    }
                )
            elif 'toolResult' in part:
                r = part['toolResult']
                results.append(
                    {
                        'role': 'tool',
                        'tool_call_id': r['toolUseId'],
                        'content': json.dumps(
                            {'status': r.get('status', 'success'), 'content': r['content']}, allow_nan=False
                        ),
                    }
                )
            else:
                raise ValueError('Unsupported message content; cannot safely translate')
        if text or calls:
            m = {'role': message['role'], 'content': '\n'.join(text) if text else None}
            if calls:
                m['tool_calls'] = calls
            messages.append(m)
        messages.extend(results)
    config = request.get('inferenceConfig', {})
    payload = {
        'model': model,
        'messages': messages,
        'max_tokens': config.get('maxTokens', 1100),
        'temperature': config.get('temperature', 0),
        'stream': False,
    }
    specs = request.get('toolConfig', {}).get('tools', [])
    if specs:
        payload['tools'] = [
            {
                'type': 'function',
                'function': {
                    'name': s['toolSpec']['name'],
                    'description': s['toolSpec']['description'],
                    'parameters': s['toolSpec']['inputSchema']['json'],
                },
            }
            for s in specs
        ]
        payload['tool_choice'] = 'auto'
    return payload


def chat_response(body):
    if body.get('error'):
        raise ValueError('Provider returned embedded error')
    choice = body['choices'][0]
    if choice.get('finish_reason') in ('length', 'content_filter'):
        raise ValueError('Incomplete or filtered model response')
    m = choice['message']
    content = []
    if isinstance(m.get('content'), str) and m['content']:
        content.append({'text': m['content']})
    ids = set()
    for call in m.get('tool_calls') or []:
        args = json.loads(call['function']['arguments'])
        if not isinstance(args, dict) or not call['id'] or call['id'] in ids:
            raise ValueError('Invalid tool call')
        ids.add(call['id'])
        content.append(
            {'toolUse': {'toolUseId': call['id'], 'name': call['function']['name'], 'input': args}}
        )
    if not content:
        raise ValueError('Empty model response')
    usage = body.get('usage') or {}
    result = {
        'output': {'message': {'role': 'assistant', 'content': content}},
        'usage': {
            'inputTokens': usage.get('prompt_tokens', 0),
            'outputTokens': usage.get('completion_tokens', 0),
        },
        'stopReason': 'tool_use' if ids else 'end_turn',
    }
    # Reasoning models return their reasoning beside the message (Groq: reasoning, vLLM: reasoning_content).
    # It is kept for the step trace only, never sent back into the conversation.
    reasoning = m.get('reasoning') or m.get('reasoning_content')
    if isinstance(reasoning, str) and reasoning.strip():
        result['reasoning'] = reasoning.strip()[:REASONING_LIMIT]
    return result


class Router:
    def __init__(self, config=None, transport=None):
        try:
            if config is None:
                path = Path(os.getenv('LLM_ROUTER_CONFIG', 'warehouse_agents/router.json'))
                config = json.loads(path.read_text())
            self.config = RouterConfig.model_validate(config)
        except Exception:
            raise ValueError(
                'Invalid router configuration; use documented fields and environment-variable key references only.'
            ) from None
        names = [r.name for r in self.config.routes]
        if len(names) != len(set(names)):
            raise ValueError('Route names must be unique')
        self.transport = transport
        self.cooldowns = {}
        self.retry_after = {}
        self.next_in_tier = {}

    async def invoke(self, route, request, client, key=None, slot=None):
        if route.api_key_env and not key:
            return None, 'missing_key', None
        if route.provider == 'bedrock':
            if not key:
                # Preserve IAM support; SDK retries disabled because this layer owns failover.
                import boto3
                from botocore.config import Config

                sdk = boto3.client(
                    'bedrock-runtime',
                    region_name=route.region,
                    config=Config(
                        connect_timeout=3,
                        read_timeout=self.config.timeout_seconds,
                        retries={'total_max_attempts': 1},
                    ),
                )
                try:
                    result = await asyncio.to_thread(sdk.converse, modelId=route.model, **request)
                    return result, None, None
                except Exception as exc:
                    status = getattr(exc, 'response', {}).get('ResponseMetadata', {}).get('HTTPStatusCode')
                    return None, 'http_error' if status else 'provider_error', status
            url = f'https://bedrock-runtime.{route.region}.amazonaws.com/model/{quote(route.model, safe="")}/converse'
            payload = request
        elif route.provider == 'openai_compatible':
            url, payload = (
                route.base_url.rstrip('/') + '/chat/completions',
                chat_request(request, route.model),
            )
        else:
            if not key:
                return None, 'missing_key', None
            base = {'groq': 'https://api.groq.com/openai/v1', 'openrouter': 'https://openrouter.ai/api/v1'}[
                route.provider
            ]
            url, payload = base + '/chat/completions', chat_request(request, route.model)
        headers = {'Authorization': 'Bearer ' + key} if key else {}
        response = await client.post(url, headers=headers, json=payload)
        if not response.is_success:
            self.retry_after[slot or route.name] = retry_after_seconds(response.headers.get('retry-after'))
            return None, 'http_error', response.status_code
        body = response.json()
        result = body if route.provider == 'bedrock' else chat_response(body)
        message = result['output']['message']
        if (
            message.get('role') != 'assistant'
            or not message.get('content')
            or result.get('stopReason') in ('max_tokens', 'content_filtered', 'guardrail_intervened')
        ):
            raise ValueError('Invalid or incomplete model response')
        return result, None, None

    async def attempt(self, route, request, client, key=None, slot=None):
        provider = 'aws.bedrock' if route.provider == 'bedrock' else route.provider
        with operation(
            'llm.provider',
            {
                'gen_ai.operation.name': 'chat',
                'gen_ai.provider.name': provider,
                'gen_ai.request.model': route.model,
                'llm.route': slot or route.name,
            },
            SpanKind.CLIENT,
        ) as span:
            started = time.perf_counter()
            try:
                async with asyncio.timeout(self.config.timeout_seconds):
                    result, error, status = await self.invoke(route, request, client, key, slot)
            except (httpx.HTTPError, TimeoutError) as exc:
                result, error, status = None, 'network_error', None
                span.set_attribute('error.type', type(exc).__name__)
            except Exception as exc:
                result, error, status = None, 'invalid_response_or_provider_error', None
                span.set_attribute('error.type', type(exc).__name__)
            if status is not None:
                span.set_attribute('http.response.status_code', status)
            if error:
                span.set_attribute('llm.outcome', error)
                span.set_status(Status(StatusCode.ERROR))
                if status:
                    span.set_attribute('error.type', 'HTTP' + str(status))
            else:
                span.set_attribute('llm.outcome', 'success')
                for field, attribute in [
                    ('inputTokens', 'gen_ai.usage.input_tokens'),
                    ('outputTokens', 'gen_ai.usage.output_tokens'),
                ]:
                    value = result.get('usage', {}).get(field)
                    if isinstance(value, (int, float)) and value >= 0:
                        span.set_attribute(attribute, int(value))
                result['latency_ms'] = round((time.perf_counter() - started) * 1000)
            return result, error, status

    def slots(self):
        """(route, key, slot name) per configured key; key is None without a key variable, '' when it is empty."""
        slots = []
        for route in self.config.routes:
            keys = split_keys(os.getenv(route.api_key_env, '')) if route.api_key_env else [None]
            if not keys:
                slots.append((route, '', route.name))
            elif len(keys) == 1:
                slots.append((route, keys[0], route.name))
            else:
                slots += [(route, k, f'{route.name}#{n}') for n, k in enumerate(keys, 1)]
        return slots

    def order(self, route=None):
        """Slots to try: tier by tier, each tier rotated from its round-robin start. Also returns tier sizes.
        With `route`, only that route's slots: the user picked a model, so never fall back to another one."""
        slots = self.slots()
        if route is not None:
            slots = [s for s in slots if s[0].name == route]
            if not slots:
                raise ValueError(f'Unknown model route: {route}')
        order, sizes = [], {}
        for tier in sorted({route.tier for route, _, _ in slots}):
            members = [s for s in slots if s[0].tier == tier]
            sizes[tier] = len(members)
            start = (
                self.next_in_tier.get(tier, 0) % len(members) if self.config.strategy == 'round_robin' else 0
            )
            order += [
                (members[(start + k) % len(members)], (start + k) % len(members)) for k in range(len(members))
            ]
        return order, sizes

    def cool_down(self, slot):
        seconds = min(MAX_COOLDOWN_SECONDS, max(self.config.cooldown_seconds, self.retry_after.pop(slot, 0)))
        self.cooldowns[slot] = time.monotonic() + seconds
        return round(seconds)

    async def converse(self, route=None, **request):
        attempts = []
        order, sizes = self.order(route)
        reserved = False
        # A 413 says this request is too large for that model's limits; other keys of the same route would
        # refuse it too, and the keys are fine for smaller requests, so skip them without a cooldown.
        too_large = set()
        try:
            async with asyncio.timeout(self.config.total_timeout_seconds):
                async with httpx.AsyncClient(
                    timeout=self.config.timeout_seconds, follow_redirects=False, transport=self.transport
                ) as client:
                    for (route, key, slot), position in order:
                        safe = {'route': slot, 'provider': route.provider, 'model': route.model}
                        if self.cooldowns.get(slot, 0) > time.monotonic():
                            attempts.append(dict(safe, status='cooldown'))
                            continue
                        if key == '':
                            attempts.append(dict(safe, status='missing_key', http_status=None))
                            continue
                        if route.name in too_large:
                            attempts.append(dict(safe, status='skipped_request_too_large'))
                            continue
                        if not reserved and self.config.strategy == 'round_robin':
                            # Reserve before awaiting network I/O, so concurrent calls rotate too.
                            self.next_in_tier[route.tier] = (position + 1) % sizes[route.tier]
                            reserved = True
                        result, error, status = await self.attempt(route, request, client, key, slot)
                        if result is not None:
                            result['routing'] = dict(
                                strategy='pinned' if route else self.config.strategy,
                                selected=dict(safe, tier=route.tier),
                                latency_ms=result.pop('latency_ms', None),
                                attempts=attempts + [dict(safe, status='success')],
                            )
                            return result
                        if status == 413:
                            too_large.add(route.name)
                            self.retry_after.pop(slot, None)
                            attempts.append(dict(safe, status=error, http_status=status))
                            continue
                        attempts.append(
                            dict(
                                safe, status=error, http_status=status, cooldown_seconds=self.cool_down(slot)
                            )
                        )
        except TimeoutError:
            attempts.append({'status': 'total_deadline'})
        raise RouterUnavailable(attempts)
