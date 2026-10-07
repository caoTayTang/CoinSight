"""Trace parentage and privacy checks; no provider calls or network export."""
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from app import telemetry, chat_agent
from botocore.exceptions import ClientError
from fastapi import HTTPException
import pytest


@pytest.fixture
def spans(monkeypatch):
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry, 'tracer', provider.get_tracer('test'))
    monkeypatch.setenv('BEDROCK_MODEL_ID', 'test-model')
    yield exporter
    provider.shutdown()


def test_chat_child_spans_match_response_trace_id(monkeypatch, spans):
    class Client:
        count = 0
        def converse(self, **_kwargs):
            self.count += 1
            content = ([{'toolUse': {'toolUseId': 't1', 'name': 'get_snapshot', 'input': {'symbol': 'BTC'}}}]
                       if self.count == 1 else [{'text': 'private response'}])
            return {'output': {'message': {'role': 'assistant', 'content': content}},
                    'usage': {'inputTokens': 12, 'outputTokens': 4}}
    client = Client()
    monkeypatch.setattr('boto3.client', lambda *_args, **_kwargs: client)
    monkeypatch.setattr(chat_agent, 'dispatch', lambda *_args: {'status': 'unavailable', 'trace_id': 'source-123'})
    result = chat_agent.chat(chat_agent.ChatRequest(message='private prompt'))
    exported = spans.get_finished_spans()
    root = next(span for span in exported if span.name == 'assistant.request')
    children = [span for span in exported if span.name != 'assistant.request']
    assert len(children) == 3
    assert all(span.parent.span_id == root.context.span_id for span in children)
    assert result.trace.trace_id == format(root.context.trace_id, '032x')
    assert root.attributes['gen_ai.usage.input_tokens'] == 24
    assert all('private' not in str(span.attributes) + str(span.events) for span in exported)


def test_provider_failure_is_error_span_without_exception_message(monkeypatch, spans):
    class Client:
        def converse(self, **_kwargs):
            raise ClientError({'Error': {'Code': 'ResourceNotFoundException', 'Message': 'private secret'}}, 'Converse')
    monkeypatch.setattr('boto3.client', lambda *_args, **_kwargs: Client())
    with pytest.raises(HTTPException) as caught:
        chat_agent.chat(chat_agent.ChatRequest(message='private prompt'))
    exported = spans.get_finished_spans()
    assert all(span.status.is_ok is False for span in exported)
    assert len(exported) == 2
    assert all(span.status.status_code.name == 'ERROR' for span in exported)
    assert caught.value.headers['X-Trace-ID'] == format(exported[-1].context.trace_id, '032x')
    assert all('private' not in str(span.attributes) + str(span.events) for span in exported)
