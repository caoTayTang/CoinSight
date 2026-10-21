# Local MCP + A2A services

A read-only prototype using the frozen BTC hourly ensemble and a separate statistical anomaly detector. No LLM/API key is required for the services themselves. An LLM or another MCP client can invoke them; there is no free-form planner or autonomous trading loop in this version.

```text
MCP client
   │ Streamable HTTP :8010/mcp
   ▼
MCP gateway
   │ A2A v1.0 / JSON-RPC SendMessage
   ▼
Prediction Agent :8011
   ├─ reads 169 closed BTC + ETH hourly candles
   ├─ sends the same BTC context to Anomaly Agent :8012 over A2A
   └─ runs the unchanged frozen ensemble; returns both results
```

The `detect_btc_anomalies` MCP tool also calls the anomaly agent directly. Each role is a separate Docker container. The optional stack is independent of the warehouse/Kafka/Spark stack.

## Start and stop

From the repository root, prepare the portable serving bundle once using the existing research runtime:

```bash
data/models/hourly-research-runtime/venv/bin/python -m scripts.prepare_agent_bundle
```

This is an export, not training. It checks both members against all 6,984 saved 2026 predictions. The maximum ensemble difference is 1.71e-15 log-return. Numeric features and model borders retain CatBoost float32 quantization. The service uses CatBoost’s official standalone Python export, so its container does not need to download the 99 MB native CatBoost library.

Then start the stack:

```bash
docker compose -p coinsight-agents -f compose.agents.yml up --build -d

docker compose -p coinsight-agents -f compose.agents.yml ps
docker compose -p coinsight-agents -f compose.agents.yml logs --tail=50

# Stop only these three services; leaves the rest of CoinSight alone.
docker compose -p coinsight-agents -f compose.agents.yml down
```

The model bundle is mounted read-only from:

```text
data/models/agent-serving-bundle/v1
```

This local artifact is ignored by Git. A fresh checkout needs the prepared bundle (`ensemble.json`, the two original `.joblib` files for identity checks, two Python exports and `serving_manifest.json`). The original trained bundle and saved 2026 evaluation snapshots are needed only for preparation. At runtime no pickle is deserialized; the original member files and exported code are hash-checked against pinned identities. `HOURLY_ENSEMBLE_DIR` can point to another directory containing the same files. Startup rejects a changed specification/model hash; building never trains or downloads a replacement model.

The default build uses `python:3.12-slim`; the serving requirements exclude native CatBoost/scikit-learn/SciPy. On this workstation, the already-installed `coinsight-pipeline:latest` image can be reused to avoid downloading the numeric runtime again:

```bash
AGENT_BASE_IMAGE=coinsight-pipeline:latest \
  docker compose -p coinsight-agents -f compose.agents.yml build

docker compose -p coinsight-agents -f compose.agents.yml up -d
```

## Connect a client

| Service | Host URL |
| --- | --- |
| MCP Streamable HTTP | `http://127.0.0.1:8010/mcp` |
| Prediction Agent Card | `http://127.0.0.1:8011/.well-known/agent-card.json` |
| Anomaly Agent Card | `http://127.0.0.1:8012/.well-known/agent-card.json` |
| A2A JSON-RPC | `http://127.0.0.1:8011/` and `http://127.0.0.1:8012/` |
| Health | `/health` on each service |

Configure an HTTP/Streamable HTTP connection in your chosen MCP client using the MCP URL above. Client-specific configuration files are not edited automatically. All ports bind only to `127.0.0.1`; authentication is not implemented for this local prototype.

Public Agent Cards advertise the host URLs. Inside Docker, the configured peer URLs use service DNS (`anomaly-agent:8000`, `prediction-agent:8000`). The official A2A SDK transport sends to that configured URL with `A2A-Version: 1.0`; it does not follow a public card URL into the wrong container.

## MCP tools

### `predict_hourly(cutoff=None)`

Default: latest closed-hour boundary from Binance server time. Optional cutoff is a timezone-aware ISO hour from 2026 onward, for example `2026-01-05T00:00:00Z`.

The target is still BTCUSDT `ln(C[t+1]/C[t])`, exactly one hour from cutoff. The response includes:

- forecast log-return, reference close, implied next close and direction;
- `cutoff`, target interval, `generated_at`, and whether the target hour has already started;
- frozen bundle identity and retrospective model evaluation context;
- anomaly checks and the delegated `anomaly_task_id`;
- paired snapshot hash, BTC anomaly-context hash and source timestamp;
- the enclosing A2A task ID/context ID.

The two CatBoost members and their weights are unchanged: `0.3718555755249541` for BTC compact and `0.18388857895182398` for BTC+ETH. Outputs are divided by 10,000 before weighting. There is no additional multiplier 0.5, calibration or fitting.

Calling at 10:20 uses the last candle closed at 10:00 and predicts the 10:00–11:00 target. It is explicitly marked as already in progress; this is not a claim that the prediction was issued at 10:00. Historical requests are marked historical.

### `detect_btc_anomalies(cutoff=None)`

Checks the latest closed BTC hour against preceding closed bars using median/MAD robust z-scores:

- one-hour log return: 167 previous returns;
- log quote volume: 168 previous bars;
- range/open: 168 previous bars.

Scale is `max(1.4826 × MAD, floor)`, with floors `1e-6`, `1e-3`, `1e-6` respectively. A fixed `abs(z) >= 6` flags a deviation. The latest observation is excluded from the reference sample. The response identifies which metrics are flagged, their direction, values and robust scores.

This is a transparent statistical baseline, not a trained anomaly classifier. It has no calibrated false-positive rate and does not identify causes, manipulation, or an event probability. An anomaly is returned alongside a valid forecast; it does not mechanically override the model. Missing/invalid context or an unavailable peer fails the request, with no fabricated fallback forecast.

## Operational bounds

Each context must contain exactly 169 ordered, contiguous, valid closed candles. Naive/misaligned/future cutoff, clock disagreement, invalid OHLCV, gaps and non-finite values are rejected. The prediction agent verifies the anomaly peer's cutoff and context hash match its input.

No warehouse writes, scheduler, periodic fetches, retraining or trade execution. The generated model code is loaded only from the trusted, hash-pinned read-only local bundle. Public Binance requests happen only on tool calls; internet access is needed for market data. The gateway has no model mount. Containers use a non-root user, read-only filesystem, bounded temporary storage and CPU/memory limits.

A2A tasks are synchronous, non-streaming, and stored in ephemeral memory; they disappear on restart. Cancellation, durable task history, authentication and production monitoring are not implemented. This is an on-demand local service, not a 30-day laptop collection job.

## Verification

Use the isolated local test runtime (not the research runtime):

```bash
uv venv --python 3.12 data/models/local-agent-runtime/venv
uv pip install --python data/models/local-agent-runtime/venv/bin/python \
  -r agents/requirements.txt pytest pytest-asyncio

data/models/local-agent-runtime/venv/bin/python -m pytest tests/agents -q

data/models/local-agent-runtime/venv/bin/python -m scripts.check_local_agents
```

`make agents-up`, `make agents-down`, `make agents-test` and `make agents-smoke` wrap the same commands. Agent tests run in a separate CI job because the current API uses an older FastAPI/Starlette dependency set; the main API environment is not upgraded.

The smoke command uses the official MCP client to list tools, request a forecast, verify an actual delegated anomaly A2A task, compare the BTC context hash against a direct anomaly call, and reject a future cutoff. It writes proof to `data/models/local-agent-runtime/smoke.json`. It does not train anything.

The optional local model test compares inference against a saved 2026 forecast, with exactly 169 input candles and no target candle. Protocol tests exercise task/artifact responses and peer-failure propagation; market tests cover closed-candle context and stale source-clock rejection.

The native CatBoost Docker download first timed out; the final serving implementation uses a parity-checked portable export instead. The original research model and its weights were not changed.

References: [CatBoost standalone Python export](https://catboost.ai/docs/en/concepts/python-reference_catboostregressor_save_model), [A2A Python SDK](https://github.com/a2aproject/a2a-python), [A2A server example](https://github.com/a2aproject/a2a-samples/tree/main/samples/python/agents/helloworld), [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk), [research report](hourly_research_summary.html).

## Verified local run

Three containers are running healthy on ports 8010/8011/8012. The deployed MCP smoke test passed with a real prediction task and a distinct delegated anomaly task; the peer context hash matched. Both modern and legacy MCP clients returned structured tool results. A future cutoff was rejected.

Local checks: 8 agent tests passed, plus 75 existing hourly decision tests. The portable export was checked on all 6,984 saved 2026 forecast rows, with maximum ensemble difference 1.71e-15 log-return. An idle Docker sample used about 220 MiB across all three containers (limits: 1 GiB prediction, 384 MiB each for anomaly and gateway). No temporary native test servers remain running.

Runtime proof: `data/models/local-agent-runtime/smoke.json`. Export proof: `data/models/agent-serving-bundle/v1/serving_manifest.json`.
