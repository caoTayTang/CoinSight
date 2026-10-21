"""A2A v1.0 structured messages through the official SDK JSON-RPC transport."""

import logging
import httpx
from google.protobuf import json_format
from a2a.helpers import new_data_message
from a2a.types import AgentCard, Role, SendMessageRequest, SendMessageConfiguration, TaskState
from a2a.client.transports.jsonrpc import JsonRpcTransport
from a2a.client.client import ClientCallContext

log = logging.getLogger(__name__)


async def call_agent(base_url: str, payload: dict, *, client: httpx.AsyncClient | None = None) -> dict:
    own = client is None
    client = client or httpx.AsyncClient(timeout=60, follow_redirects=False)
    try:
        response = await client.get(base_url.rstrip('/') + '/.well-known/agent-card.json')
        response.raise_for_status()
        card = json_format.ParseDict(response.json(), AgentCard())
        if not any(
            i.protocol_binding == 'JSONRPC' and i.protocol_version == '1.0' for i in card.supported_interfaces
        ):
            raise ValueError('Peer does not advertise supported A2A v1 JSONRPC')
        message = new_data_message(payload, media_type='application/json', role=Role.ROLE_USER)
        # Use configured peer URL; advertised public URL can differ on the Docker network.
        transport = JsonRpcTransport(client, card, base_url.rstrip('/') + '/')
        log.info('a2a.send peer=%s message_id=%s', card.name, message.message_id)
        result = await transport.send_message(
            SendMessageRequest(
                message=message, configuration=SendMessageConfiguration(return_immediately=False)
            ),
            context=ClientCallContext(service_parameters={'A2A-Version': '1.0'}),
        )
        if not result.HasField('task'):
            raise ValueError('Peer did not return an A2A task')
        task = result.task
        if task.status.state != TaskState.TASK_STATE_COMPLETED:
            detail = '; '.join(p.text for p in task.status.message.parts if p.text)
            raise RuntimeError(f'{card.name}: task failed: {detail or TaskState.Name(task.status.state)}')
        for artifact in task.artifacts:
            for part in artifact.parts:
                if part.HasField('data'):
                    value = json_format.MessageToDict(part.data)
                    if not isinstance(value, dict):
                        raise ValueError('Peer artifact must be an object')
                    return dict(task_id=task.id, context_id=task.context_id, result=value)
        raise ValueError('Peer completed without a structured result artifact')
    finally:
        if own:
            await client.aclose()
