"""Driver/task tracing with W3C context; never records payloads or credentials."""
from contextlib import contextmanager
from functools import wraps
import os
import json
from opentelemetry import trace, propagate
from opentelemetry.trace import Status, StatusCode

_provider = None
_pid = None


def configure():
    global _provider, _pid
    endpoint = os.getenv('OTEL_EXPORTER_OTLP_TRACES_ENDPOINT')
    if not endpoint:
        return trace.get_tracer('coinsight.pipeline')
    if _pid != os.getpid():
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        _provider = TracerProvider(resource=Resource.create({
            'service.name': os.getenv('OTEL_SERVICE_NAME', 'coinsight-pipeline')}))
        _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, timeout=5)))
        _pid = os.getpid()
    return _provider.get_tracer('coinsight.pipeline')


@contextmanager
def operation(name, attributes=None, context=None):
    with configure().start_as_current_span(name, attributes=attributes or {}, context=context,
                                          record_exception=False, set_status_on_exception=False) as span:
        try:
            yield span
        except Exception as error:
            span.set_attribute('error.type', type(error).__name__)
            span.set_status(Status(StatusCode.ERROR))
            raise


def traced(name):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            attrs = {'spark.batch_id': args[2]} if len(args) > 2 and isinstance(args[2], int) else {}
            with operation(name, attrs):
                return fn(*args, **kwargs)
        return wrapped
    return decorate


def current_trace_id():
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, '032x') if context.is_valid else 'disabled'


def kafka_headers():
    carrier = {}
    propagate.inject(carrier)
    return [(key, value.encode('ascii')) for key, value in carrier.items()]


def link_kafka_rows(rows):
    """Bound fan-in; unlinked rows are counted, not silently claimed as traced."""
    span = trace.get_current_span()
    span.set_attribute('pipeline.rows_received', len(rows))
    contexts = {}
    for row in rows:
        carrier = {header.key: bytes(header.value).decode('ascii', errors='ignore')
                   for header in (getattr(row, 'headers', None) or []) if header.value is not None}
        context = trace.get_current_span(propagate.extract(carrier)).get_span_context()
        if context.is_valid:
            contexts[(context.trace_id, context.span_id)] = context
    for context in list(contexts.values())[:128]:
        span.add_link(context)
    span.set_attribute('messaging.linked_contexts', min(len(contexts), 128))
    span.set_attribute('messaging.omitted_contexts', max(0, len(contexts) - 128))
    if rows:
        span.set_attribute('messaging.offset.min', min(row.offset for row in rows))
        span.set_attribute('messaging.offset.max', max(row.offset for row in rows))
        span.set_attribute('messaging.partitions', sorted({row.partition for row in rows}))


def airflow_task(fn):
    """Trace one task attempt, propagate through existing dict XCom results."""
    @wraps(fn)
    def wrapped(*args, **kwargs):
        from airflow.sdk import get_current_context
        current = get_current_context()
        ti = current['ti']
        carrier = next((value['_trace_context'] for value in args
                        if isinstance(value, dict) and '_trace_context' in value), {})
        try:
            with operation(f'airflow.task.{ti.task_id}', {
                'airflow.dag_id': ti.dag_id, 'airflow.run_id': current['run_id'],
                'airflow.task_id': ti.task_id, 'airflow.try_number': ti.try_number,
            }, context=propagate.extract(carrier)) as span:
                print(json.dumps({'event': 'airflow.task.trace', 'trace_id': current_trace_id(),
                                  'dag_id': ti.dag_id, 'task_id': ti.task_id,
                                  'run_id': current['run_id'], 'attempt': ti.try_number}), flush=True)
                result = fn(*args, **kwargs)
                if isinstance(result, dict):
                    result = dict(result)
                    for key in ('batch_id', 'rows_staged', 'rows_loaded', 'rows_rejected', 'status'):
                        if isinstance(result.get(key), (str, int, float, bool)):
                            span.set_attribute(f'pipeline.{key}', result[key])
                    result['_trace_context'] = {}
                    propagate.inject(result['_trace_context'])
                return result
        finally:
            if _provider is not None:
                _provider.force_flush(timeout_millis=5000)
    return wrapped
