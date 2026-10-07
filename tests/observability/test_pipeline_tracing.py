from types import SimpleNamespace
from unittest.mock import Mock
import sys
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pipeline import telemetry
import pytest


@pytest.fixture
def spans(monkeypatch):
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry, 'configure', lambda: provider.get_tracer('pipeline-test'))
    yield exporter
    provider.shutdown()


def test_kafka_context_links_to_consumer(spans):
    with telemetry.operation('kafka.publish') as producer:
        headers = telemetry.kafka_headers()
        context = producer.get_span_context()
    rows = [SimpleNamespace(headers=[SimpleNamespace(key=k, value=v) for k, v in headers], offset=4, partition=0)]
    with telemetry.operation('spark.candles.commit'):
        telemetry.link_kafka_rows(rows)
    consumer = spans.get_finished_spans()[-1]
    assert consumer.links[0].context.trace_id == context.trace_id
    assert consumer.links[0].context.span_id == context.span_id
    assert consumer.attributes['pipeline.rows_received'] == 1
    assert consumer.attributes['messaging.offset.min'] == 4


def test_legacy_rows_without_headers_are_still_observable(spans):
    with telemetry.operation('spark.candles.commit'):
        telemetry.link_kafka_rows([SimpleNamespace(offset=1, partition=0)])
    assert spans.get_finished_spans()[-1].attributes['messaging.linked_contexts'] == 0


def test_airflow_xcom_links_attempts_and_preserves_result(monkeypatch, spans):
    ti = SimpleNamespace(task_id='extract', dag_id='daily', try_number=1)
    monkeypatch.setitem(sys.modules, 'airflow.sdk', SimpleNamespace(get_current_context=lambda: {'ti': ti, 'run_id': 'manual-test'}))
    @telemetry.airflow_task
    def extract():
        return {'batch_id': 12, 'rows_staged': 20}
    @telemetry.airflow_task
    def load(summary):
        return {'batch_id': summary['batch_id'], 'rows_loaded': 20}
    result = extract()
    ti.task_id = 'load'
    ti.try_number = 2
    assert load(result)['rows_loaded'] == 20
    parent, child = spans.get_finished_spans()
    assert child.parent.span_id == parent.context.span_id
    assert child.attributes['airflow.try_number'] == 2
    assert result['batch_id'] == 12


def test_producer_dedup_and_headers_do_not_change_event(tmp_path, spans):
    from pipeline.stream.kafka_publisher import LivePublisher
    producer = Mock()
    producer.send.return_value.get.return_value = SimpleNamespace(partition=0, offset=2)
    event = {'event_id': 'event1', 'event_time': '2026-10-07T00:00:00+00:00', 'symbol': 'BTC', 'pair': 'BTCUSDT', 'source': 'test'}
    publisher = LivePublisher(producer, 'topic', tmp_path / 'state.json')
    publisher.publish(event)
    publisher.publish(event)
    assert producer.send.call_count == 1
    assert producer.send.call_args.kwargs['value'] == event
    assert dict(producer.send.call_args.kwargs['headers'])['traceparent']


def test_publish_failure_does_not_advance_checkpoint(tmp_path, spans):
    from pipeline.stream.kafka_publisher import LivePublisher
    producer = Mock()
    producer.send.return_value.get.side_effect = TimeoutError('private transport error')
    publisher = LivePublisher(producer, 'topic', tmp_path / 'state.json')
    with pytest.raises(TimeoutError):
        publisher.publish({'event_id': 'e1', 'event_time': '2026-10-07T00:00:00+00:00',
                           'symbol': 'BTC', 'pair': 'BTCUSDT', 'source': 'test'})
    assert publisher.last_open == {}
    assert not (tmp_path / 'state.json').exists()
    span = spans.get_finished_spans()[-1]
    assert span.status.status_code.name == 'ERROR'
    assert 'private' not in str(span.attributes) + str(span.events)


def test_fan_in_links_are_bounded_and_omissions_counted(spans):
    rows = []
    for offset in range(130):
        with telemetry.operation('publish'):
            headers = telemetry.kafka_headers()
        rows.append(SimpleNamespace(headers=[SimpleNamespace(key=k, value=v) for k, v in headers], offset=offset, partition=0))
    with telemetry.operation('consume'):
        telemetry.link_kafka_rows(rows)
    span = spans.get_finished_spans()[-1]
    assert len(span.links) == 128
    assert span.attributes['messaging.omitted_contexts'] == 2
