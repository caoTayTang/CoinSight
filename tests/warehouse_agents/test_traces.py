import json
import httpx
import pytest
from warehouse_agents import traces


def envelope():
    return {
        'result': {
            'resourceSpans': [
                {
                    'resource': {
                        'attributes': [{'key': 'service.name', 'value': {'stringValue': 'coinsight-api'}}]
                    },
                    'scopeSpans': [
                        {
                            'spans': [
                                {
                                    'traceId': 'a' * 32,
                                    'spanId': 'b' * 16,
                                    'name': 'warehouse.query',
                                    'startTimeUnixNano': '1000000000',
                                    'endTimeUnixNano': '1020000000',
                                    'status': {'code': 2},
                                    'attributes': [
                                        {'key': 'error.type', 'value': {'stringValue': 'ConnectError'}},
                                        {'key': 'http.response.status_code', 'value': {'intValue': '503'}},
                                        {'key': 'db.statement', 'value': {'stringValue': 'PRIVATE_SQL'}},
                                        {'key': 'authorization', 'value': {'stringValue': 'PRIVATE_TOKEN'}},
                                    ],
                                    'events': [{'name': 'PRIVATE_EXCEPTION'}],
                                }
                            ]
                        }
                    ],
                }
            ]
        }
    }


def test_trace_metadata_has_errors_and_timing_but_no_sensitive_attributes_or_events():
    rows = traces.span_rows([envelope()])
    assert rows[0]['error'] and rows[0]['duration_ms'] == 20
    assert rows[0]['attributes'] == {'error.type': 'ConnectError', 'http.response.status_code': '503'}
    assert 'PRIVATE' not in json.dumps(rows)
    assert traces.summary(rows)['duration_ms'] == 20
    data = envelope()
    data['result']['resourceSpans'][0]['resource']['attributes'][0]['value']['stringValue'] = (
        'unrelated-service'
    )
    assert traces.span_rows([data]) == []


@pytest.mark.asyncio
async def test_search_and_inspect_use_v3_bounded_parameters_and_known_trace_ids(monkeypatch):
    calls = []

    async def fake(path, params=None):
        calls.append((path, params))
        return traces.span_rows([envelope()])

    monkeypatch.setattr(traces, 'query', fake)
    found = await traces.search_traces('coinsight-api', 30, 2)
    assert found['traces'][0]['error_spans'] == 1 and calls[0][1]['query.num_traces'] == 2
    inspected = await traces.inspect_trace('A' * 32)
    assert inspected['spans'][0]['offset_ms'] == 0 and inspected['trace_id'] == 'a' * 32
    assert calls[-1][0] == '/api/v3/traces/' + 'a' * 32
    for args in [('http://evil', 30, 1), ('coinsight-api', True, 1), ('coinsight-api', 1, 6)]:
        with pytest.raises(ValueError):
            await traces.search_traces(*args)
    with pytest.raises(ValueError):
        await traces.inspect_trace('../secrets')


@pytest.mark.asyncio
async def test_jaeger_stream_cap_and_error_propagation(monkeypatch):
    original = httpx.AsyncClient

    def respond(request):
        return httpx.Response(200, content=b'x' * 1048577)

    monkeypatch.setattr(
        traces.httpx,
        'AsyncClient',
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    with pytest.raises(ValueError, match='1 MiB'):
        await traces.query('/api/v3/traces')
    with pytest.raises(ValueError):
        traces.span_rows([{'error': {'message': 'PRIVATE'}}])


def test_sre_has_trace_tools_but_market_agent_delegates():
    from warehouse_agents.graph import OPS, ANALYST, SPECS

    assert {'search_traces', 'inspect_trace'} <= OPS.keys()
    assert 'inspect_trace' not in ANALYST and 'investigate_warehouse' in ANALYST
    assert SPECS['inspect_trace']['toolSpec']['inputSchema']['json']['required'] == ['trace_id']


@pytest.mark.asyncio
async def test_empty_search_is_not_confused_with_missing_api(monkeypatch):
    original = httpx.AsyncClient

    def client(**kwargs):
        return original(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(404, json={'error': {'httpCode': 404, 'message': 'No traces found'}})
            ),
            **kwargs,
        )

    monkeypatch.setattr(traces.httpx, 'AsyncClient', client)
    assert await traces.query('/api/v3/traces') == []
    monkeypatch.setattr(
        traces.httpx,
        'AsyncClient',
        lambda **kwargs: original(
            transport=httpx.MockTransport(lambda r: httpx.Response(404, text='404 page not found')), **kwargs
        ),
    )
    with pytest.raises(httpx.HTTPStatusError):
        await traces.query('/api/v3/traces')
