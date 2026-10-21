"""Reproducible live acceptance: MCP + trained model + real LLM delegation + negative request."""

import argparse
import asyncio
import json
import os
from pathlib import Path
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from contextlib import asynccontextmanager
import httpx2


async def run(url, output, market_only=False):
    headers = (
        {'Authorization': 'Bearer ' + os.environ['WAREHOUSE_AGENT_TOKEN']}
        if os.getenv('WAREHOUSE_AGENT_TOKEN')
        else None
    )

    @asynccontextmanager
    async def transport():
        async with httpx2.AsyncClient(headers=headers or {}, timeout=300) as http:
            async with streamable_http_client(url, http_client=http) as streams:
                yield streams[:2]

    async with Client(transport(), read_timeout_seconds=300) as client:
        names = [t.name for t in (await client.list_tools()).tools]
        assert set(names) == {'market_anomaly', 'model_health', 'ask_analyst', 'ask_operations'}
        proof = {'tools': names}
        for name in ('market_anomaly', 'model_health'):
            reply = await client.call_tool(name, {})
            assert not reply.is_error, str(reply.content)
            assert reply.structured_content['status'] == 'available'
            proof[name] = reply.structured_content
            print(name + ': PASS', flush=True)
        cutoff = proof['market_anomaly']['source']['cutoff']
        # Same frozen hour should produce precisely the same forest score.
        repeat = await client.call_tool('market_anomaly', {'cutoff': cutoff})
        assert repeat.structured_content['trained'] == proof['market_anomaly']['trained']
        proof['same_cutoff_reproducible'] = True
        invalid = await client.call_tool('market_anomaly', {'cutoff': '2099-01-01T00:00:00Z'})
        assert invalid.is_error
        proof['future_cutoff_rejected'] = True
        output.parent.mkdir(parents=True, exist_ok=True)
        proof['real_llm_a2a_acceptance'] = 'skipped' if market_only else 'pending'
        output.write_text(json.dumps(proof, indent=2, default=str))
        if market_only:
            print('Market acceptance PASS; LLM acceptance skipped explicitly.', flush=True)
            return
        reply = await client.call_tool(
            'ask_analyst',
            {
                'question': 'Delegate to Operations agent via investigate_warehouse: inspect BTC last 24 closed-hour warehouse coverage and Airflow DAG availability. '
                'Do not substitute a market prediction. Report any unavailable evidence honestly.'
            },
        )
        if reply.is_error:
            proof['real_llm_a2a_acceptance'] = 'failed'
            proof['error'] = (
                'Analyst A2A tool failed; inspect sanitized service logs for provider/connectivity cause.'
            )
            output.write_text(json.dumps(proof, indent=2, default=str))
            raise RuntimeError(proof['error'])
        result = reply.structured_content['result']
        delegated = [e for e in result['evidence'] if e['tool'] == 'investigate_warehouse']
        assert delegated, 'LLM failed to delegate'
        peer = delegated[0]['result']
        assert peer['status'] == 'available' and peer['task_id'] != reply.structured_content['task_id']
        assert peer['result']['role'] == 'operations' and peer['result']['evidence']
        assert result['answer'], 'No final answer generated'
        proof['analyst_to_operations'] = reply.structured_content
        proof['real_llm_a2a_acceptance'] = 'passed'
        print('MCP -> Analyst LLM -> A2A Operations LLM -> evidence -> answer: PASS', flush=True)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(proof, indent=2, default=str))
        print('Saved: ' + str(output), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url', default='http://127.0.0.1:8020/mcp')
    p.add_argument(
        '--output', type=Path, default=Path('data/models/warehouse-agent-validation/live_acceptance.json')
    )
    p.add_argument(
        '--market-only',
        action='store_true',
        help='Skip paid Bedrock calls explicitly; does not certify live reasoning.',
    )
    args = p.parse_args()
    asyncio.run(run(args.url, args.output, args.market_only))
