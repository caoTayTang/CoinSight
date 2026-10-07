"""OpenTelemetry traces exported over OTLP/HTTP to Jaeger.

Only operational metadata is recorded. No prompts, responses, raw SQL,
credentials or provider exception messages are attached to spans.
"""
from contextlib import contextmanager
from functools import wraps
import os

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

_provider = None
tracer = trace.get_tracer('coinsight.api')


def configure_tracing():
    global _provider
    endpoint = os.getenv('OTEL_EXPORTER_OTLP_TRACES_ENDPOINT')
    if _provider is not None or not endpoint:
        return _provider
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    _provider = TracerProvider(resource=Resource.create({
        'service.name': os.getenv('OTEL_SERVICE_NAME', 'coinsight-api'),
    }))
    _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, timeout=5)))
    trace.set_tracer_provider(_provider)
    return _provider


@contextmanager
def operation(name, attributes=None):
    with tracer.start_as_current_span(name, attributes=attributes or {},
                                     record_exception=False, set_status_on_exception=False) as span:
        try:
            yield span
        except Exception as error:
            span.set_attribute('error.type', type(error).__name__)
            span.set_status(Status(StatusCode.ERROR))
            raise


def traced(name):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with operation(name):
                return function(*args, **kwargs)
        return wrapped
    return decorate


def current_trace_id():
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, '032x') if context.is_valid else None
