from app import api
from app.chat_agent import ChatRequest, chat, dispatch
from fastapi import HTTPException
from botocore.exceptions import ClientError
import pytest


def test_agent_tools_are_whitelisted(monkeypatch):
    monkeypatch.setattr(api, 'asset_snapshot', lambda symbol: api.Envelope[api.Snapshot](
        status='unavailable', data=None, trace_id='test',
        provenance=api.Provenance(source='binance', mode='historical'),
        quality=api.Quality()))
    assert dispatch('get_snapshot', {'symbol': 'BTC'})['status'] == 'unavailable'
    try:
        dispatch('run_sql', {'symbol': 'BTC'})
    except ValueError:
        pass
    else:
        assert False, 'arbitrary SQL must not be available'


def test_expired_bedrock_token_is_reported_as_unavailable(monkeypatch):
    class ExpiredClient:
        def converse(self, **_kwargs):
            raise ClientError({"Error": {"Code": "AccessDeniedException",
                                         "Message": "Bearer Token has expired"}}, "Converse")

    monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model")
    monkeypatch.setattr("boto3.client", lambda *_args, **_kwargs: ExpiredClient())
    with pytest.raises(HTTPException) as error:
        chat(ChatRequest(message="hello"))
    assert error.value.status_code == 503
    assert "expired" in error.value.detail


def test_trace_records_model_and_tool_events_without_prompt_logs(monkeypatch, caplog):
    import logging
    from app import chat_agent

    class Client:
        calls = 0

        def converse(self, **_kwargs):
            self.calls += 1
            content = ([{'toolUse': {'toolUseId': 'tool-1', 'name': 'get_snapshot',
                                     'input': {'symbol': 'BTC'}}}] if self.calls == 1
                       else [{'text': 'No verified price available.'}])
            return {'output': {'message': {'role': 'assistant', 'content': content}},
                    'usage': {'inputTokens': 10, 'outputTokens': 5}}

    client = Client()
    monkeypatch.setenv('BEDROCK_MODEL_ID', 'test-model')
    monkeypatch.setattr('boto3.client', lambda *_args, **_kwargs: client)
    monkeypatch.setattr(chat_agent, 'dispatch', lambda *_args: {'status': 'unavailable', 'data': None})
    with caplog.at_level(logging.INFO, logger='uvicorn.error'):
        result = chat(ChatRequest(message='private test prompt'))
    assert result.trace.model_calls == 2
    assert result.trace.input_tokens == 20
    assert result.trace.output_tokens == 10
    assert [(event.kind, event.status) for event in result.trace.events] == [
        ('model', 'success'), ('tool', 'unavailable'), ('model', 'success')]
    assert result.trace.trace_id in caplog.text
    assert 'private test prompt' not in caplog.text
    assert result.answer not in caplog.text


def test_provider_error_has_correlated_trace(monkeypatch, caplog):
    import logging

    class Client:
        def converse(self, **_kwargs):
            raise ClientError({'Error': {'Code': 'ResourceNotFoundException',
                                         'Message': 'provider private detail'}}, 'Converse')

    monkeypatch.setenv('BEDROCK_MODEL_ID', 'test-model')
    monkeypatch.setattr('boto3.client', lambda *_args, **_kwargs: Client())
    with caplog.at_level(logging.INFO, logger='uvicorn.error'), pytest.raises(HTTPException) as error:
        chat(ChatRequest(message='hello'))
    trace_id = error.value.headers['X-Trace-ID']
    assert trace_id in error.value.detail
    assert trace_id in caplog.text
    assert 'ResourceNotFoundException' in caplog.text
    assert 'provider private detail' not in caplog.text
