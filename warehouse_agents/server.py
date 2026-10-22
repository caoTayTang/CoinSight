"""A2A endpoints for actual bounded reasoning agents; separate from predictor services."""

import asyncio
import logging
import os
from pathlib import Path
from google.protobuf import json_format
from a2a.helpers import new_task_from_user_message, new_data_part, new_text_message
from a2a.server.agent_execution import AgentExecutor
from a2a.server.tasks import TaskUpdater, InMemoryTaskStore
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.types import AgentCard, AgentInterface, AgentSkill, AgentCapabilities, TaskState
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from warehouse_agents.graph import Reasoner
from warehouse_agents.runtime import BoundedTaskStore, LocalGuard
from warehouse_agents.telemetry import TraceMiddleware, operation, trace_id


class Turn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: Literal['user', 'assistant']
    text: str = Field(max_length=4000)


class Request(BaseModel):
    model_config = ConfigDict(extra='forbid')
    question: str = Field(min_length=1, max_length=3000)
    symbol: str = Field(default='BTC', pattern='^(BTC|ETH|SOL)$')
    # Earlier turns of the conversation, the router route the user picked, and the user's memory key.
    history: list[Turn] = Field(default_factory=list, max_length=12)
    model: str | None = Field(default=None, pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    user: str | None = Field(default=None, pattern=r'^(local|u_[a-f0-9]{16})$')


class Executor(AgentExecutor):
    def __init__(self, role, reasoner=None):
        self.reasoner = reasoner or Reasoner(role)
        self.lock = asyncio.Semaphore(2)

    async def execute(self, context, event_queue):
        task = context.current_task or new_task_from_user_message(context.message)
        if not context.current_task:
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.update_status(TaskState.TASK_STATE_WORKING)
        try:
            if context.current_task:
                raise ValueError('Continuation unsupported; submit a new task')
            parts = context.message.parts
            if len(parts) != 1 or not parts[0].HasField('data'):
                raise ValueError('Exactly one JSON data part required')
            request = Request.model_validate(json_format.MessageToDict(parts[0].data))
            # Reject saturated workers promptly; peers must not wait through an unbounded queue.
            async with asyncio.timeout(1):
                await self.lock.acquire()
            try:
                with operation(
                    'agent.task',
                    {
                        'a2a.task.id': task.id,
                        'gen_ai.agent.name': 'trade' if self.reasoner.role == 'analyst' else 'sre',
                    },
                ):
                    result = await self.reasoner.run(
                        request.question + '\nRequested asset: ' + request.symbol,
                        history=[t.model_dump() for t in request.history],
                        model=request.model,
                        user=request.user,
                    )
            finally:
                self.lock.release()
            result['task_id'] = task.id
            await updater.add_artifact(
                parts=[new_data_part(result, media_type='application/json')], name='investigation'
            )
            await updater.update_status(TaskState.TASK_STATE_COMPLETED)
            logging.getLogger(__name__).info(
                'task.completed role=%s task_id=%s calls=%s', self.reasoner.role, task.id, result['llm_calls']
            )
        except Exception as exc:
            # Never return raw SDK errors containing request bodies or connection credentials.
            logging.getLogger(__name__).warning('task.failed task_id=%s type=%s', task.id, type(exc).__name__)
            from warehouse_agents.router import RouterUnavailable

            if isinstance(exc, RouterUnavailable):
                logging.getLogger(__name__).warning(
                    'router.exhausted task_id=%s attempts=%s', task.id, exc.attempts
                )
            await updater.update_status(
                TaskState.TASK_STATE_FAILED,
                message=new_text_message('Investigation failed: ' + type(exc).__name__),
            )

    async def cancel(self, context, event_queue):
        raise NotImplementedError('Bounded synchronous investigations do not support cancellation')


def create_app(role=None, reasoner=None):
    role = role or os.getenv('WAREHOUSE_AGENT_ROLE', 'analyst')
    if reasoner is None:
        from warehouse_agents.router import Router

        reasoner = Reasoner(role, backend=Router())
    executor = Executor(role, reasoner)
    public = os.getenv('AGENT_PUBLIC_URL', 'http://127.0.0.1:' + ('8021' if role == 'analyst' else '8022'))
    description = 'Read-only multi-provider LLM reasoning over allowlisted market and warehouse evidence using LangGraph.'
    card = AgentCard(
        name='CoinSight ' + ('Trade' if role == 'analyst' else 'SRE'),
        description=description,
        version='1.0.0',
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=['application/json'],
        default_output_modes=['application/json'],
        supported_interfaces=[
            AgentInterface(protocol_binding='JSONRPC', url=public + '/', protocol_version='1.0')
        ],
        skills=[
            AgentSkill(id=role, name=role.title(), description=description, tags=['warehouse', 'research'])
        ],
    )
    handler = DefaultRequestHandler(executor, BoundedTaskStore(), agent_card=card, validate_input_modes=True)

    async def health(_):
        return JSONResponse(
            {
                'status': 'ok',
                'role': role,
                'llm_router_configured': Path(
                    os.getenv('LLM_ROUTER_CONFIG', 'warehouse_agents/router.json')
                ).is_file(),
                'task_store': 'ephemeral_memory',
                'read_only_tools': True,
            }
        )

    return Starlette(
        routes=create_agent_card_routes(card)
        + create_jsonrpc_routes(handler, '/')
        + [Route('/health', health)]
    )


app = TraceMiddleware(LocalGuard(create_app()))
if __name__ == '__main__':
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        app, host='0.0.0.0', port=int(os.getenv('PORT', '8000')), limit_concurrency=16, timeout_keep_alive=5
    )
