import httpx
import pytest
from agents import server
from agents.rpc import call_agent
from tests.agents.test_domain import context


@pytest.mark.asyncio
async def test_anomaly_a2a_card_task_and_structured_artifact():
    app = server.create_app('anomaly')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
        result = await call_agent(
            'http://test',
            dict(operation='detect_anomalies', context=context().model_dump(mode='json')),
            client=client,
        )
        assert result['task_id'] and result['context_id']
        assert result['result']['agent'] == 'anomaly'
        assert result['result']['is_anomaly'] is False
        with pytest.raises(RuntimeError, match='task failed'):
            await call_agent('http://test', dict(operation='bad_operation'), client=client)


@pytest.mark.asyncio
async def test_forecaster_must_delegate_same_candles_and_fail_if_peer_down(monkeypatch):
    ctx = context()
    snapshot = dict(
        contexts={'BTC': ctx.model_dump(mode='json'), 'ETH': ctx.model_dump(mode='json')},
        snapshot_sha256='paired-test',
        source='fixture',
        observed_server_time=ctx.cutoff.isoformat(),
    )

    async def market(*args, **kwargs):
        return snapshot

    monkeypatch.setattr(server, 'load_context', market)
    anomaly = server.create_app('anomaly')
    calls = []

    async def peer(url, payload):
        calls.append(payload)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(anomaly), base_url='http://anomaly'
        ) as client:
            return await call_agent('http://anomaly', payload, client=client)

    monkeypatch.setattr(server, 'call_agent', peer)
    from agents import prediction

    monkeypatch.setattr(
        prediction,
        'predict',
        lambda btc, eth: dict(predicted_log_return=0.001, cutoff=btc.cutoff.isoformat()),
    )
    app = server.create_app('prediction')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
        reply = await call_agent('http://test', dict(operation='predict_hourly'), client=client)
        assert reply['result']['anomaly_task_id'] and calls[0]['context'] == snapshot['contexts']['BTC']
        assert reply['result']['snapshot_sha256'] == 'paired-test'

        async def broken(*args, **kwargs):
            raise RuntimeError('peer unavailable')

        monkeypatch.setattr(server, 'call_agent', broken)
        with pytest.raises(RuntimeError, match='peer unavailable'):
            await call_agent('http://test', dict(operation='predict_hourly'), client=client)


@pytest.mark.asyncio
async def test_daily_forecast_support_contract_delegates_without_hourly_snapshot(monkeypatch):
    from agents import prediction

    calls = []

    def support(**kwargs):
        calls.append(kwargs)
        return {'status': 'ready', 'symbol': kwargs['symbol']}

    monkeypatch.setattr(prediction, 'forecast_support', support)
    app = server.create_app('prediction')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
        reply = await call_agent(
            'http://test',
            dict(
                operation='forecast_support', symbol='ETH', performance_days=14,
                market_days=21, trend_hours=72,
            ),
            client=client,
        )
    assert reply['result']['status'] == 'ready'
    assert calls == [dict(
        symbol='ETH', performance_days=14, market_days=21,
        trend_hours=72, cutoff=None,
    )]
