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
from pydantic import BaseModel, ConfigDict
from typing import Literal
from agents.domain import CandleContext, detect_anomalies, context_digest
from agents.market import load_context
from agents.rpc import call_agent

ROLE = os.getenv('AGENT_ROLE', 'prediction')
ANOMALY_URL = os.getenv('ANOMALY_AGENT_URL', 'http://127.0.0.1:8012')


class PredictionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation: Literal['predict_hourly'] = 'predict_hourly'
    cutoff: str | None = None


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
                    snapshot = await load_context(request.cutoff)
                    btc = CandleContext.model_validate(snapshot['contexts']['BTC'])
                    eth = CandleContext.model_validate(snapshot['contexts']['ETH'])
                    # This is an actual peer A2A task, not an in-process detector call.
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
        'Frozen BTC next-hour log-return forecast with delegated A2A anomaly inspection.'
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
                tags=['BTC', 'hourly', role],
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

    @asynccontextmanager
    async def lifespan(_app):
        if role == 'prediction':
            from agents.prediction import frozen_models

            await asyncio.to_thread(frozen_models)
        yield

    return Starlette(routes=routes, lifespan=lifespan)


app = create_app()
if __name__ == '__main__':
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host='0.0.0.0', port=int(os.getenv('PORT', '8000')))
