"""MCP tools delegate work to discoverable A2A services; no forecasting in this gateway."""

import os
from typing import Any, Literal
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
from starlette.routing import Route
from agents.rpc import call_agent

PREDICTION_URL = os.getenv('PREDICTION_AGENT_URL', 'http://127.0.0.1:8011')
ANOMALY_URL = os.getenv('ANOMALY_AGENT_URL', 'http://127.0.0.1:8012')
mcp = MCPServer(
    'CoinSight Local Agents',
    version='0.1.0',
    instructions='BTC/ETH research-support tools. forecast_support may repair only its bounded required warehouse ranges before running a daily model. '
    'Quantiles are empirical uncertainty estimates, not guaranteed probabilities or trading instructions.',
)


@mcp.tool(
    structured_output=True,
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)
async def forecast_support(
    symbol: Literal['BTC', 'ETH'] = 'BTC',
    performance_days: int = 30,
    market_days: int = 30,
    trend_hours: int = 168,
    cutoff: str | None = None,
) -> dict[str, Any]:
    """Forecast the next UTC daily close for BTC/ETH with quantiles and diagnostics.

    The service audits its exact daily/hourly input ranges first. It only performs
    targeted Binance archive/REST staging and warehouse UPSERT when gaps exist.
    """
    return await call_agent(PREDICTION_URL, dict(
        operation='forecast_support', symbol=symbol,
        performance_days=performance_days, market_days=market_days,
        trend_hours=trend_hours, cutoff=cutoff,
    ))


@mcp.tool(
    structured_output=True,
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
async def detect_btc_anomalies(cutoff: str | None = None) -> dict[str, Any]:
    """Inspect closed BTC hourly return/volume/range with past-only robust median/MAD scores.

    Optional ISO cutoff; this is a fixed statistical detector, not a trained event classifier.
    """
    return await call_agent(ANOMALY_URL, dict(operation='detect_anomalies', cutoff=cutoff))


security = TransportSecuritySettings(
    allowed_hosts=['127.0.0.1:*', 'localhost:*', 'mcp-gateway:*'],
    allowed_origins=['http://127.0.0.1:*', 'http://localhost:*'],
)
app = mcp.streamable_http_app(
    stateless_http=True, json_response=True, host='0.0.0.0', transport_security=security
)


async def health(_):
    return JSONResponse(dict(status='ok', transport='MCP Streamable HTTP', path='/mcp'))


app.routes.append(Route('/health', health))
if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host='0.0.0.0', port=int(os.getenv('PORT', '8000')))
