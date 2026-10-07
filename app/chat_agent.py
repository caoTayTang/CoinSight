"""Read-only Bedrock assistant grounded in the public DSS API contracts."""
from __future__ import annotations

import os
import json
import logging
from time import perf_counter
from uuid import uuid4
from opentelemetry import trace as otel_trace
try:
    from .telemetry import traced, operation, current_trace_id
except ImportError:
    from telemetry import traced, operation, current_trace_id
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ChatEvent(BaseModel):
    kind: str
    name: str
    status: str
    duration_ms: int


class ChatTrace(BaseModel):
    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    model_calls: int = 0
    events: list[ChatEvent] = Field(default_factory=list)


class ChatResponse(BaseModel):
    answer: str
    tools_used: list[str]
    model_id: str
    trace: ChatTrace | None = None


TOOLS = [
    {
        "toolSpec": {
            "name": name,
            "description": description,
            "inputSchema": {"json": {"type": "object", "properties": {
                "symbol": {"type": "string", "enum": ["BTC", "ETH", "SOL"]}},
                "required": ["symbol"]}},
        }
    }
    for name, description in (
        ("get_snapshot", "Latest closed UTC daily Binance Spot USDT candle with source and freshness"),
        ("get_live_summary", "Latest 15 minutes of closed one-minute candles with coverage and freshness"),
        ("get_direction_prediction", "Validated next-day direction probability and model evaluation"),
    )
]
TOOLS.append({"toolSpec": {
    "name": "get_model_evaluation",
    "description": "Latest model-vs-baseline evaluation and acceptance decision",
    "inputSchema": {"json": {"type": "object", "properties": {}}},
}})


def dispatch(name: str, parameters: dict[str, Any]) -> dict:
    # Import here to avoid a cycle during FastAPI route registration.
    try:
        from . import api
    except ImportError:
        import api

    if name == "get_model_evaluation":
        return api.model_evaluation().model_dump(mode="json")

    symbol = parameters.get("symbol")
    if symbol not in {"BTC", "ETH", "SOL"}:
        raise ValueError("symbol must be BTC, ETH, or SOL")
    functions = {
        "get_snapshot": api.asset_snapshot,
        "get_live_summary": api.live_summary,
        "get_direction_prediction": api.direction_prediction,
    }
    if name not in functions:
        raise ValueError("unknown tool")
    return functions[name](symbol).model_dump(mode="json")


@traced("assistant.request")
def chat(request: ChatRequest) -> ChatResponse:
    trace = ChatTrace(trace_id=current_trace_id() or str(uuid4()))
    started = perf_counter()
    status = 'error'
    error_type = None
    try:
        response = _chat(request, trace)
        status = 'success'
        return response
    except HTTPException as error:
        error_type = f'HTTP_{error.status_code}'
        error.headers = {**(error.headers or {}), 'X-Trace-ID': trace.trace_id}
        error.detail = f'{error.detail} · Reference: {trace.trace_id}'
        raise
    except Exception as error:
        error_type = type(error).__name__
        raise HTTPException(status_code=502,
                            detail=f'Assistant failed · Reference: {trace.trace_id}',
                            headers={'X-Trace-ID': trace.trace_id}) from error
    finally:
        trace.duration_ms = round((perf_counter() - started) * 1000)
        span = otel_trace.get_current_span()
        span.set_attribute('assistant.status', status)
        span.set_attribute('assistant.model_calls', trace.model_calls)
        span.set_attribute('gen_ai.usage.input_tokens', trace.input_tokens)
        span.set_attribute('gen_ai.usage.output_tokens', trace.output_tokens)
        # Metadata only: never log prompts, answers, credentials or raw tool payloads.
        logging.getLogger('uvicorn.error').info(json.dumps({
            'event': 'assistant.request', 'status': status, 'error_type': error_type,
            'model_id': os.getenv('BEDROCK_MODEL_ID'), **trace.model_dump(),
        }))


def _chat(request: ChatRequest, trace: ChatTrace) -> ChatResponse:
    model_id = os.getenv("BEDROCK_MODEL_ID")
    if not model_id:
        raise HTTPException(status_code=503, detail="BEDROCK_MODEL_ID is not configured")
    import boto3
    from botocore.exceptions import ClientError

    client = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1"))
    messages = [{"role": "user", "content": [{"text": request.message}]}]
    used = []
    system = [{"text": (
        "You are CoinSight's analysis assistant. Answer in the user's language. "
        "Write like a concise market desk brief: lead with the result, then key numbers and timestamps. "
        "Avoid greetings, promotional language, tutorials and self-description. "
        "Use at most three short bullets unless the user asks for detail. "
        "Use the tools for all market facts. Never invent prices, probabilities, "
        "freshness, or data lineage. Distinguish observed data from prediction. "
        "If a tool says unavailable, stale, or insufficient_data, state that plainly. "
        "Do not give personalized trading instructions."
    )}]
    for _ in range(5):
        model_started = perf_counter()
        trace.model_calls += 1
        try:
            with operation('bedrock.converse', {'gen_ai.request.model': model_id}) as span:
                try:
                    response = client.converse(modelId=model_id, system=system, messages=messages,
                                              toolConfig={"tools": TOOLS}, inferenceConfig={"maxTokens": 600})
                except ClientError as error:
                    span.set_attribute('aws.error.code', error.response.get('Error', {}).get('Code', 'unknown'))
                    raise
                usage = response.get('usage', {})
                span.set_attribute('gen_ai.usage.input_tokens', usage.get('inputTokens', 0))
                span.set_attribute('gen_ai.usage.output_tokens', usage.get('outputTokens', 0))
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "")
            trace.events.append(ChatEvent(kind='model', name='converse', status=code or 'error',
                                          duration_ms=round((perf_counter() - model_started) * 1000)))
            detail = error.response.get("Error", {}).get("Message", "").lower()
            if code == "AccessDeniedException" and "expired" in detail:
                raise HTTPException(status_code=503, detail="Bedrock token expired; update AWS_BEARER_TOKEN_BEDROCK") from error
            if code == "AccessDeniedException":
                raise HTTPException(status_code=503, detail="Bedrock access denied; check model access and credentials") from error
            raise HTTPException(status_code=502, detail=f"Bedrock request failed ({code or 'unknown error'})") from error
        except Exception as error:
            trace.events.append(ChatEvent(kind='model', name='converse', status=type(error).__name__,
                                          duration_ms=round((perf_counter() - model_started) * 1000)))
            raise
        trace.events.append(ChatEvent(kind='model', name='converse', status='success',
                                      duration_ms=round((perf_counter() - model_started) * 1000)))
        usage = response.get('usage', {})
        trace.input_tokens += usage.get('inputTokens', 0)
        trace.output_tokens += usage.get('outputTokens', 0)
        output = response["output"]["message"]
        messages.append(output)
        calls = [item["toolUse"] for item in output["content"] if "toolUse" in item]
        if not calls:
            answer = "\n".join(item["text"] for item in output["content"] if "text" in item)
            return ChatResponse(answer=answer, tools_used=used, model_id=model_id, trace=trace)
        results = []
        for call in calls:
            name = call["name"]
            used.append(name)
            tool_started = perf_counter()
            tool_status = 'error'
            try:
                safe_name = name if name in {item['toolSpec']['name'] for item in TOOLS} else 'unknown'
                with operation(f'assistant.tool.{safe_name}') as span:
                    payload = dispatch(name, call.get("input", {}))
                    tool_status = payload.get('status', 'success')
                    span.set_attribute('tool.result.status', tool_status)
                    if isinstance(payload.get('trace_id'), str):
                        span.set_attribute('data.trace_id', payload['trace_id'])
            except ValueError as error:
                payload = {"error": str(error)}
            finally:
                known_names = {item['toolSpec']['name'] for item in TOOLS}
                trace.events.append(ChatEvent(kind='tool', name=name if name in known_names else 'unknown_tool',
                                              status=tool_status,
                                              duration_ms=round((perf_counter() - tool_started) * 1000)))
            results.append({"toolResult": {"toolUseId": call["toolUseId"],
                                            "content": [{"json": payload}]}})
        messages.append({"role": "user", "content": results})
    raise HTTPException(status_code=502, detail="Agent exceeded tool call limit")
