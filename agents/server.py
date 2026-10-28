"""Prediction and anomaly A2A agents; run each role in its own container."""

import asyncio, logging, os
from contextlib import asynccontextmanager
from google.protobuf import json_format
from a2a.helpers import new_task_from_user_message, new_data_part, new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater, InMemoryTaskStore
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.types import AgentCard, AgentInterface, AgentSkill, AgentCapabilities, TaskState
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal
from agents.domain import CandleContext, detect_anomalies, context_digest
from agents.market import load_context
from agents.rpc import call_agent

ROLE = os.getenv('AGENT_ROLE', 'prediction')
ANOMALY_URL = os.getenv('ANOMALY_AGENT_URL', 'http://127.0.0.1:8012')


class PredictionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation: Literal['forecast_support', 'predict_hourly'] = 'forecast_support'
    symbol: Literal['BTC', 'ETH'] = 'BTC'
    performance_days: int = Field(default=30, ge=7, le=365)
    market_days: int = Field(default=30, ge=7, le=365)
    trend_hours: int = Field(default=168, ge=24, le=1000)
    cutoff: str | None = None

    @model_validator(mode='after')
    def legacy_contract(self):
        if self.operation == 'predict_hourly' and (
            self.symbol != 'BTC'
            or self.performance_days != 30
            or self.market_days != 30
            or self.trend_hours != 168
        ):
            raise ValueError('legacy predict_hourly accepts BTC and cutoff only')
        return self


class AnomalyRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation: Literal['detect_anomalies'] = 'detect_anomalies'
    context: CandleContext | None = None
    cutoff: str | None = None


class Executor(AgentExecutor):
    def __init__(self, role):
        self.role = role
        self.lock = asyncio.Semaphore(2)

    async def execute(self, context: RequestContext, event_queue: EventQueue):
        task = context.current_task or new_task_from_user_message(context.message)
        if not context.current_task:
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.update_status(TaskState.TASK_STATE_WORKING)
        try:
            if context.current_task:
                raise ValueError('Task continuation is not supported; send a new message')
            parts = [p for p in context.message.parts if p.HasField('data')]
            if len(parts) != 1 or len(context.message.parts) != 1:
                raise ValueError('Send one application/json data part')
            payload = json_format.MessageToDict(parts[0].data)
            async with self.lock:
                if self.role == 'anomaly':
                    request = AnomalyRequest.model_validate(payload)
                    if request.context is None:
                        snapshot = await load_context(request.cutoff, assets=('BTC',))
                        ctx = CandleContext.model_validate(snapshot['contexts']['BTC'])
                    else:
                        ctx = request.context
                        if request.cutoff is not None:
                            raise ValueError('Use context or cutoff, not both')
                    result = detect_anomalies(ctx)
                else:
                    request = PredictionRequest.model_validate(payload)
                    if request.operation == 'forecast_support':
                        from agents.prediction import forecast_support

                        result = await asyncio.to_thread(
                            forecast_support,
                            symbol=request.symbol,
                            performance_days=request.performance_days,
                            market_days=request.market_days,
                            trend_hours=request.trend_hours,
                            cutoff=request.cutoff,
                        )
                    else:
                        snapshot = await load_context(request.cutoff)
                        btc = CandleContext.model_validate(snapshot['contexts']['BTC'])
                        eth = CandleContext.model_validate(snapshot['contexts']['ETH'])
                        # Rollback route keeps the original peer anomaly check intact.
                        anomaly = await call_agent(
                            ANOMALY_URL, dict(operation='detect_anomalies', context=btc.model_dump(mode='json'))
                        )
                        if anomaly['result'].get('cutoff') != btc.cutoff.isoformat() or anomaly['result'].get(
                            'context_sha256'
                        ) != context_digest(btc):
                            raise ValueError('Peer context mismatch')
                        from agents.prediction import predict

                        result = await asyncio.to_thread(predict, btc, eth)
                        result.update(
                            anomaly=anomaly['result'],
                            anomaly_task_id=anomaly['task_id'],
                            snapshot_sha256=snapshot['snapshot_sha256'],
                            source=snapshot['source'],
                            observed_server_time=snapshot['observed_server_time'],
                        )
                result['task_id'] = task.id
            await updater.add_artifact(
                parts=[new_data_part(result, media_type='application/json')], name=self.role + '_result'
            )
            await updater.update_status(TaskState.TASK_STATE_COMPLETED)
            logging.getLogger(__name__).info('task.completed role=%s task_id=%s', self.role, task.id)
        except Exception as exc:
            logging.getLogger(__name__).exception('task.failed role=%s task_id=%s', self.role, task.id)
            # Fail the task explicitly. No invented fallback prediction if source or peer fails.
            await updater.update_status(
                TaskState.TASK_STATE_FAILED, message=new_text_message(f'{type(exc).__name__}: {exc}')
            )

    async def cancel(self, context, event_queue):
        raise NotImplementedError('Short synchronous tasks do not support cancellation')


def create_app(role=ROLE):
    if role not in ('prediction', 'anomaly'):
        raise ValueError('Unknown agent role')
    public = os.getenv('AGENT_PUBLIC_URL', f'http://127.0.0.1:{8011 if role == "prediction" else 8012}')
    description = (
        'BTC/ETH next-UTC-daily-close support forecast with quantiles and recent diagnostics.'
        if role == 'prediction'
        else 'Past-only median/MAD checks on the last closed BTC hourly candle.'
    )
    card = AgentCard(
        name='CoinSight ' + role.title() + ' Agent',
        description=description,
        version='0.1.0',
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=['application/json'],
        default_output_modes=['application/json'],
        supported_interfaces=[
            AgentInterface(protocol_binding='JSONRPC', url=public + '/', protocol_version='1.0')
        ],
        skills=[
            AgentSkill(
                id=role,
                name=role.title(),
                description=description,
                tags=['BTC', 'ETH', 'daily', role] if role == 'prediction' else ['BTC', 'hourly', role],
                input_modes=['application/json'],
                output_modes=['application/json'],
            )
        ],
    )
    handler = DefaultRequestHandler(
        Executor(role), InMemoryTaskStore(), agent_card=card, validate_input_modes=True
    )

    async def health(_):
        return JSONResponse(dict(status='ok', role=role, protocol='A2A v1.0', task_store='ephemeral_memory'))

    routes = create_agent_card_routes(card) + create_jsonrpc_routes(handler, '/') + [Route('/health', health)]
    if role == 'prediction':
        from agents.backtest_api import create_backtest, get_backtest
        routes += [
            Route('/policy-backtests', create_backtest, methods=['POST']),
            Route('/policy-backtests/{job_id}', get_backtest, methods=['GET']),
        ]

    @asynccontextmanager
    async def lifespan(_app):
        if role == 'prediction':
            from pipeline.decision.serving.model_bundle import ForecastModelBundle

            # Fail startup instead of serving an unverified/missing active bundle.
            await asyncio.gather(*(
                asyncio.to_thread(ForecastModelBundle.load, symbol)
                for symbol in ('BTC', 'ETH')
            ))
        yield

    return Starlette(routes=routes, lifespan=lifespan)


app = create_app()
if __name__ == '__main__':
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host='0.0.0.0', port=int(os.getenv('PORT', '8000')))
