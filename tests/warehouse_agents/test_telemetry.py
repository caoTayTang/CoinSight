import asyncio
import json
import httpx
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from warehouse_agents.telemetry import operation, trace_id, TraceMiddleware
from warehouse_agents.peer import PropagatingClient
from warehouse_agents.router import Router


@pytest.fixture(scope='module')
def exporter():
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    out = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(out))
    return out


@pytest.fixture(autouse=True)
def clear(exporter):
    exporter.clear()


def test_errors_record_type_without_message_or_stack(exporter):
    with pytest.raises(RuntimeError):
        with operation('safe.operation'):
            raise RuntimeError('PRIVATE_ERROR_BODY')
    s = exporter.get_finished_spans()[-1]
    assert s.status.status_code.name == 'ERROR'
    assert s.attributes['error.type'] == 'RuntimeError'
    assert not s.events and 'PRIVATE_ERROR_BODY' not in str(s.attributes)


@pytest.mark.asyncio
async def test_router_failed_attempt_tokens_and_no_content(exporter, monkeypatch):
    monkeypatch.setenv('TRACE_TEST_KEY', 'PRIVATE_PROVIDER_KEY')
    config = {
        'routes': [
            {'name': 'first', 'provider': 'groq', 'model': 'one', 'api_key_env': 'TRACE_TEST_KEY'},
            {'name': 'second', 'provider': 'openrouter', 'model': 'two', 'api_key_env': 'TRACE_TEST_KEY'},
        ]
    }

    def respond(req):
        if 'groq' in req.url.host:
            return httpx.Response(429, json={'error': {'message': 'PRIVATE_BODY'}})
        return httpx.Response(
            200,
            json={
                'choices': [{'finish_reason': 'stop', 'message': {'content': 'PRIVATE_ANSWER'}}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 20},
            },
        )

    with operation('root'):
        root = trace_id()
        await Router(config, httpx.MockTransport(respond)).converse(
            messages=[{'role': 'user', 'content': [{'text': 'PRIVATE_PROMPT'}]}]
        )
    spans = exporter.get_finished_spans()
    providers = [s for s in spans if s.name == 'llm.provider']
    assert len(providers) == 2 and all(format(s.context.trace_id, '032x') == root for s in spans)
    assert (
        providers[0].attributes['http.response.status_code'] == 429
        and providers[0].status.status_code.name == 'ERROR'
    )
    assert providers[1].attributes['gen_ai.usage.input_tokens'] == 10
    assert providers[1].attributes['gen_ai.usage.output_tokens'] == 20
    data = str([(dict(s.attributes), list(s.events), s.status.description) for s in spans])
    for private in ('PRIVATE_BODY', 'PRIVATE_ANSWER', 'PRIVATE_PROMPT', 'PRIVATE_PROVIDER_KEY'):
        assert private not in data


@pytest.mark.asyncio
async def test_propagation_does_not_mutate_shared_client_headers(exporter):
    got = {}

    async def respond(req):
        got[req.url.path] = req.headers['traceparent']
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), headers={'Authorization': 'Bearer PRIVATE'}
    ) as client:
        proxy = PropagatingClient(client)

        async def request(path):
            with operation('request'):
                expected = trace_id()
                await asyncio.sleep(0.01)
                await proxy.post('http://peer' + path, json={})
                return path, expected

        results = await asyncio.gather(request('/one'), request('/two'))
        for path, expected in results:
            assert got[path].split('-')[1] == expected
        assert 'traceparent' not in client.headers and client.headers['Authorization'] == 'Bearer PRIVATE'


@pytest.mark.asyncio
async def test_incoming_w3c_context_reaches_server_span_and_response(exporter):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.responses import JSONResponse

    async def endpoint(request):
        return JSONResponse({'trace_id': trace_id()})

    app = TraceMiddleware(Starlette(routes=[Route('/desk/command', endpoint, methods=['POST'])]))
    expected = '1234567890abcdef1234567890abcdef'
    parent = '1234567890abcdef'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as c:
        r = await c.post('/desk/command', headers={'traceparent': f'00-{expected}-{parent}-01'})
    assert r.headers['x-trace-id'] == expected and r.json()['trace_id'] == expected
    span = exporter.get_finished_spans()[-1]
    assert format(span.parent.span_id, '016x') == parent


def test_sdk_build_request_propagates_context(exporter):
    from warehouse_agents.peer import PropagatingClient
    import httpx
    from warehouse_agents.telemetry import operation

    with httpx.Client(headers={'Authorization': 'Bearer dummy'}) as client:
        with operation('parent') as span:
            request = PropagatingClient(client).build_request('POST', 'http://peer/', json={})
            assert format(span.get_span_context().trace_id, '032x') in request.headers['traceparent']
            assert request.headers['Authorization'] == 'Bearer dummy'
        assert 'traceparent' not in client.headers
