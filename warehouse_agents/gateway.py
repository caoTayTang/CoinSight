"""Read-only MCP access to the trained detector and reasoning A2A services."""

import os
from typing import Any
import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.responses import JSONResponse
from starlette.routing import Route
from warehouse_agents.peer import call_agent
from warehouse_agents import tools
from warehouse_agents.runtime import LocalGuard
from warehouse_agents.telemetry import TraceMiddleware

mcp = MCPServer(
    'CoinSight Warehouse Intelligence',
    version='1.0.0',
    instructions='Read-only forecast and warehouse research. Agents use Bedrock/LangGraph. '
    'Forecasts are returns, not probabilities. No automatic remediation.',
)
annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)


# Production-disabled: uncomment the decorator to expose the preserved experimental detector.
# @mcp.tool(structured_output=True, annotations=annotations)
async def market_anomaly(symbol: str = 'BTC', cutoff: str | None = None) -> dict[str, Any]:
    """Score the latest closed hourly and daily BTC/ETH candles with pinned per-asset models."""
    return await tools.detect_market_anomaly(symbol=symbol, cutoff=cutoff)


# Production-disabled with the legacy anomaly/hourly reference artifacts. Keep
# the function for offline evaluation and deliberate reactivation.
# @mcp.tool(structured_output=True, annotations=annotations)
async def model_health(cutoff: str | None = None) -> dict[str, Any]:
    """Read feature PSI drift; do not interpret drift as current forecast accuracy."""
    return await tools.model_health(cutoff)


@mcp.tool(structured_output=True, annotations=annotations)
async def load_skill(name: str) -> dict[str, Any]:
    """Instructions for one kind of CoinSight request: missing-candles, warehouse-reconciliation, model-drift,
    service-unreachable, market-brief, incident-report, forecast-explainer. Not live observations."""
    return await tools.load_skill(name)


@mcp.tool(structured_output=True, annotations=annotations)
async def ask_analyst(question: str, symbol: str = 'BTC') -> dict[str, Any]:
    """Ask the market reasoning agent, which can delegate warehouse investigation through A2A."""
    async with httpx.AsyncClient(timeout=270, follow_redirects=False, headers=tools.peer_headers()) as client:
        return await call_agent(
            os.getenv('ANALYST_AGENT_URL', 'http://127.0.0.1:8021'),
            {'question': question, 'symbol': symbol},
            client=client,
        )


@mcp.tool(structured_output=True, annotations=annotations)
async def ask_operations(question: str, symbol: str = 'BTC') -> dict[str, Any]:
    """Ask the warehouse Operations agent to inspect read-only database/Airflow evidence."""
    return await tools.investigate_warehouse(question, symbol)


security = TransportSecuritySettings(
    allowed_hosts=['127.0.0.1:*', 'localhost:*', 'warehouse-mcp:*'],
    allowed_origins=['http://127.0.0.1:*', 'http://localhost:*'],
)
app = mcp.streamable_http_app(
    stateless_http=True, json_response=True, host='0.0.0.0', transport_security=security
)


async def health(_):
    return JSONResponse({'status': 'ok', 'path': '/mcp', 'scope': 'local_read_only'})


app.routes.append(Route('/health', health))
from warehouse_agents.desk import endpoint as desk_endpoint, memories_endpoint, models_endpoint, trace_endpoint

app.routes.append(Route('/desk/command', desk_endpoint, methods=['POST']))
app.routes.append(Route('/desk/models', models_endpoint, methods=['GET']))
app.routes.append(Route('/desk/traces/{trace_id:str}', trace_endpoint, methods=['GET']))
app.routes.append(Route('/desk/memories', memories_endpoint, methods=['GET']))
app.routes.append(Route('/desk/memories/{key:str}', memories_endpoint, methods=['DELETE']))
app = TraceMiddleware(LocalGuard(app))
if __name__ == '__main__':
    # Production-disabled together with the public market_anomaly MCP tool. The implementation and
    # artifacts remain available for offline experiments and can be re-enabled deliberately.
    # from pipeline.decision.anomaly.bundle import MarketAnomalyBundle
    # for asset in ('BTC', 'ETH'):
    #     for interval in ('1h', '1d'):
    #         MarketAnomalyBundle.load(asset, interval)
    import uvicorn

    uvicorn.run(app, host='0.0.0.0', port=int(os.getenv('PORT', '8000')), limit_concurrency=16)
