"""MCP tools delegate work to discoverable A2A services; no forecasting in this gateway."""

import os
from typing import Any
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
    instructions='Read-only BTC research tools. predict_hourly delegates via A2A to Prediction Agent, which asks Anomaly Agent about the same closed candles. '
    'Forecasts are log returns, not probabilities; inspect cutoff, timing, anomaly flags and research limitations.',
)


@mcp.tool(
    structured_output=True,
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
async def predict_hourly(cutoff: str | None = None) -> dict[str, Any]:
    """Predict BTCUSDT next-hour log return and inspect the latest closed candle for anomalies.

    cutoff: optional timezone-aware ISO hour (2026 onward); default latest closed-hour boundary.
    The target hour may already be in progress when called. Output records generation time.
    Uses the unchanged two-CatBoost research ensemble; no training or trading actions.
    """
    return await call_agent(PREDICTION_URL, dict(operation='predict_hourly', cutoff=cutoff))


@mcp.tool(
    structured_output=True,
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
async def detect_btc_anomalies(cutoff: str | None = None) -> dict[str, Any]:
    """Inspect closed BTC hourly return/volume/range with past-only robust median/MAD scores.

    Optional ISO cutoff as in predict_hourly; this is a fixed statistical detector, not a trained event classifier.
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
