"""Metadata-only OpenTelemetry spans and W3C trace context. Never record content/credentials."""

from contextlib import contextmanager
from functools import wraps
import inspect
import os
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

_provider = None
tracer = trace.get_tracer('coinsight.warehouse_agents')
propagator = TraceContextTextMapPropagator()


def configure_tracing():
    global _provider
    endpoint = os.getenv('OTEL_EXPORTER_OTLP_TRACES_ENDPOINT')
    if _provider is not None or not endpoint:
        return _provider
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    _provider = TracerProvider(
        resource=Resource.create(
            {'service.name': os.getenv('OTEL_SERVICE_NAME', 'coinsight-warehouse-agent')}
        )
    )
    _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, timeout=3)))
    trace.set_tracer_provider(_provider)
    return _provider


def trace_id():
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, '032x') if ctx.is_valid else None


def trace_headers():
    headers = {}
    propagator.inject(headers)
    return headers


@contextmanager
def operation(name, attributes=None, kind=SpanKind.INTERNAL, context=None):
    with tracer.start_as_current_span(
        name,
        attributes=attributes or {},
        kind=kind,
        context=context,
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except BaseException as exc:
            span.set_attribute('error.type', type(exc).__name__)
            span.set_status(Status(StatusCode.ERROR))
            raise


def traced(name, attributes=None):
    def decorate(fn):
        if inspect.iscoroutinefunction(fn):

            @wraps(fn)
            async def wrapped(*args, **kwargs):
                with operation(name, attributes):
                    return await fn(*args, **kwargs)
        else:

            @wraps(fn)
            def wrapped(*args, **kwargs):
                with operation(name, attributes):
                    return fn(*args, **kwargs)

        return wrapped

    return decorate


class TraceMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            configure_tracing()
            try:
                return await self.app(scope, receive, send)
            finally:
                if _provider:
                    _provider.force_flush(timeout_millis=3000)
        if scope['type'] != 'http' or scope['path'] == '/health':
            return await self.app(scope, receive, send)
        headers = {
            k.decode().lower(): v.decode()
            for k, v in scope['headers']
            if k.lower() in (b'traceparent', b'tracestate') and len(v) < 512
        }
        ctx = propagator.extract(headers)
        path = (
            scope['path']
            if scope['path'] in ('/', '/mcp', '/desk/command', '/.well-known/agent-card.json')
            else '/other'
        )
        with operation(
            'http.request', {'http.request.method': scope['method'], 'http.route': path}, SpanKind.SERVER, ctx
        ) as span:

            async def response(message):
                if message['type'] == 'http.response.start':
                    status = message['status']
                    span.set_attribute('http.response.status_code', status)
                    if status >= 400:
                        span.set_status(Status(StatusCode.ERROR))
                    tid = trace_id()
                    if tid:
                        message = dict(
                            message,
                            headers=list(message.get('headers', [])) + [(b'x-trace-id', tid.encode())],
                        )
                await send(message)

            return await self.app(scope, receive, response)
