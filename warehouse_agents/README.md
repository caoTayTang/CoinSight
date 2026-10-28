# CoinSight warehouse intelligence

Local, containerized market and warehouse investigation with two **LLM reasoning agents**. Provider/model/key failover is configured in `router.json`; see [ROUTER.md](ROUTER.md) for Bedrock, Groq and OpenRouter setup. The predictor remains active; the experimental Isolation Forest implementation is retained but disabled in production.

```text
MCP client :8020
  |-- market_anomaly ---> [production-disabled; offline implementation retained]
  |-- model_health -----> legacy feature PSI path (production-disabled; offline only)
  |-- ask_analyst ------> Analyst :8021 [Bedrock + LangGraph]
  |                         |-- forecast tool ---> existing prediction A2A :8011
  |                         |-- anomaly / drift tools
  |                         `-- investigate_warehouse [A2A task]
  `-- ask_operations ------------------------------|
                                                    v
                              Operations :8022 [Bedrock + LangGraph]
                                |-- PostgreSQL: coverage, lineage, reconciliation
                                |                 quality checks, fact/mart parity
                                |-- Airflow 3 REST API: DAGs / runs
                                `-- configured HTTP service reachability
```

The reasoning graph is `START -> reason -> tools -> reason -> END`. An LLM chooses among role-specific tools, sees structured evidence, and writes an answer. Tool calls are schema-validated before execution. Analyst has no SQL or shell tool; Operations has only fixed, parameterized reads. Operations cannot delegate back to Analyst, preventing recursive A2A loops.

## Start and stop

Run from the repository root. Docker Desktop and the existing `coinsight-local-agents:0.1.0` image are prerequisites. This image already contains the A2A/MCP runtime and the shared `agents`/`pipeline` modules; this extension deliberately does not rebuild or change the existing forecast services.

```sh
docker compose --env-file .env -f warehouse_agents/compose.yml build analyst
docker compose --env-file .env -f warehouse_agents/compose.yml up -d --no-build
docker compose --env-file .env -f warehouse_agents/compose.yml ps
```

Endpoints:

| Service | Endpoint | Purpose |
|---|---|---|
| MCP | `http://127.0.0.1:8020/mcp` | Four structured read-only tools |
| Analyst | `http://127.0.0.1:8021/` | A2A JSON-RPC 1.0 |
| Operations | `http://127.0.0.1:8022/` | A2A JSON-RPC 1.0 |
| Both agents | `/.well-known/agent-card.json` | A2A discovery |
| All services | `/health` | Process liveness; **not** dependency readiness |

Only this extension is stopped by:

```sh
docker compose --env-file .env -f warehouse_agents/compose.yml down
```

No continuous training, polling schedule, trading, DAG restart or database mutation runs. Work happens on request; the laptop does not need to run for 30 days.

## Configuration

The full resolved runtime is recorded in `requirements.lock`; the Docker build installs that lock. Direct dependency choices are listed in `requirements.txt`.

The configured round-robin ring is Groq GPT-OSS 120B -> OpenRouter Gemma 4 31B Free -> Bedrock Haiku 4.5 -> Bedrock Nova 2 Lite. Edit `router.json` to select models and rotation order without changing the main application model. Missing keys and cooled routes are skipped. Existing `.env` values `AWS_REGION` and `AWS_BEARER_TOKEN_BEDROCK` are forwarded at runtime. Standard AWS credentials/session token are also supported. Credentials are not copied into the image. Use an IAM identity limited to the intended Bedrock model/inference profile.

Optional variables, supplied through the environment or `.env`:

| Variable | Default / meaning |
|---|---|
| `LLM_ROUTER_CONFIG` | `/config/router.json` inside Docker; mounted from `warehouse_agents/router.json`. |
| `WAREHOUSE_AGENT_TOKEN` | Empty = trusted localhost only; nonempty enables bearer auth on MCP and both A2A services. Forwarded on internal A2A requests. |
| `WAREHOUSE_AGENT_DATABASE_URL` | Container host PostgreSQL `5432/crypto_dw`; use a dedicated observer login for deployment. |
| `WAREHOUSE_AGENT_AIRFLOW_URL` | `http://host.docker.internal:8081` |
| `AIRFLOW_API_TOKEN` | Airflow 3 API bearer token; no automatic login or token refresh |

Airflow integration targets **Airflow 3 `/api/v2`**. Airflow 2 requires an adapter; it is not silently treated as compatible. Authentication failure is `unavailable`. Warehouse schemas must include `postgres/init/05_warehouse_proof.sql` (or migration 005).

For a dedicated database observer, review and manually apply [read_only_role.sql](read_only_role.sql), set its password separately, and configure its connection URI. The tool transactions additionally set read-only mode, UTC, a 4-second SQL timeout and a 3-second connection timeout. No caller-provided SQL or database identifier is accepted. The script is supplied for deployment; it is not applied to the running application warehouse by this extension.

Container configuration currently targets Docker Desktop (`host.docker.internal`). On Linux, configure equivalent host routing or shared service networking before deployment. Do not expose these ports remotely without an authenticated TLS proxy, appropriate network policy and an explicit identity/authorization design. A shared bearer key is suitable for a trusted local deployment, not multi-tenant authorization.

## Trained anomaly model

Artifact directory: `data/models/warehouse-anomaly/v1/` (ignored local artifacts; back it up separately). Runtime mounts it read-only at `/models/anomaly`.

| Item | Frozen choice / result |
|---|---|
| Algorithm | Isolation Forest, 256 trees, max_samples 512, seed 42, n_jobs 2 |
| Features | 10 causal features: normalized return/body/range, volume/trades, 6h momentum/volatility and candle shape |
| Minimum history | 169 contiguous valid closed BTC hourly candles |
| Training | Detection cutoffs 2023–2024; 17,375 feature rows |
| Calibration | 2025; 8,760 rows |
| Threshold | 2025 score 99th percentile, `higher`; **0.6055684921806122** |
| Retrospective test | Same 6,984 cutoffs as saved 2026 forecast evaluation, through Oct 18 |
| Forest alerts | **78 / 6,984 = 1.1168%** |
| Fixed MAD alerts | **101 / 6,984 = 1.4462%** on identical timestamps |
| Accuracy / precision / recall | **Unknown: no labeled anomaly ground truth** |

A lower alert count does not establish a better detector or fewer false positives. The test was already viewed in earlier research: this is a retrospective evaluation, not a new untouched holdout. The fixed plan precedes training; no model/threshold selection on 2026 was performed in this run. The training split uses detection cutoffs, which need not equal the forecast training row count.

A score is `-IsolationForest.score_samples(features)`; larger means more unusual. Alert when score >= frozen threshold. The forest learns feature distributions without normal/anomaly labels. A market anomaly can be a perfectly valid observation. Top feature deviations describe context and are **not causal forest attribution**.

Rolling normalization uses prior hours; the scored candle is already closed. Gaps/invalid input do not get filled to fabricate a feature vector. Source calls validate contiguous hourly kline boundaries, closed candles, clock agreement and OHLC values. Future/non-hour/timezone-naive cutoffs are rejected. The API can still revise historical source data: snapshot SHA identifies fetched content; rerun equality assumes the same underlying candles.

Artifacts include sealed `plan.json`, `model.json`, `report.json`, model binary, individual test scores and frozen training/feature source copies. Model reload is verified. JSON and model hashes detect corruption; they are not cryptographic publisher signatures. Joblib bundles must come from a trusted local source. Do not load an arbitrary user-uploaded model.

To reproduce training, recover the exact source snapshots named in `train_anomaly.py`, install the pinned requirements, and run:

```sh
python -m warehouse_agents.train_anomaly
```

It refuses to overwrite `v1`. A future model version requires a separate output directory and a new frozen experiment plan, rather than silently replacing this deployment.

## Model and warehouse health interpretation

The production-disabled `model_health` implementation computes PSI on 168 feature rows from 336 raw candles against legacy training bins. It is retained for offline research and must not be presented as health evidence for the current daily quantile model. PSI >= 0.25 was a heuristic watch flag, not a statistical test or proof the forecast was failing.

Warehouse tools inspect actual operational evidence:

- Coverage: uses the archive loader source code `binance`; expected closed UTC hours versus observed asset/source grain; reports missing and duplicated hours. Listing dates/backfills must be considered when interpreting missing hours.
- Lineage: latest facts and archive hashes; absent lineage remains null.
- Reconciliation: staging = rejected + duplicates + accepted, using loader accounting; changed rows are separately reported.
- Quality: persisted validation outcomes, including failed checks on otherwise valid market data.
- Mart parity: fact candle counts and quote-volume totals against the asset subtotal (`trading_session='ALL'`, hour null). A stale mart can fail parity even if every raw sample is valid.
- Airflow: DAG state/run evidence only. No DAG mutation, task-log execution or remediation.
- Service probes: HTTP reachability only; no invented Kafka lag, disk, container, or end-to-end freshness claims.

A healthy `/health` means the process is running. A missing warehouse/Airflow connection produces an explicit `unavailable` tool result; the agent must not turn that into “everything is healthy.”

## Runtime controls and failure behavior

- Maximum four LLM responses per agent investigation; maximum eight tools in one response. Graph recursion is bounded; Operations has a 90-second wall budget and Analyst 240 seconds. Delegation has a 110-second tool deadline.
- Maximum two concurrent reasoning investigations per service, with a one-second admission deadline; HTTP concurrency limit 16.
- The LLM router attempts each eligible route once, defaults to 15 seconds per route and 45 seconds total, and cools failed routes for 30 seconds. SDK retries are disabled; SQL and other HTTP reads also have deadlines. No unbounded network retry loop.
- Request body limit 32 KiB with a 10-second body deadline; question limit 3,000 characters; 60 POST requests/minute per service (shared process budget, not per-user billing quotas).
- Tool evidence is bounded to 24 KB per response; oversized output is marked truncated. Tool failures return a sanitized unavailable observation, with no fabricated fallback prediction.
- A2A errors omit raw exception text. Completion logs record task ID, role and LLM call count; results expose tool evidence, peer task IDs and token usage. Do not log bearer tokens or connection URIs.
- Task storage is in memory, bounded to 256 tasks with a one-hour TTL. Restart loses tasks; no durable resumability or cross-worker task recovery is promised. Archive result artifacts externally if required.
- Containers run as nonroot UID 10001, with read-only filesystem/model mount, dropped capabilities, no-new-privileges, 768 MiB memory, two CPUs and bounded logs per service.

This is a hardened **local research deployment**. Public or multi-user production additionally needs TLS/identity, durable audit/task persistence, secret lifecycle, monitored operational SLOs and your own rollout process. These capabilities are not implied by a passing smoke test.

## Tests and acceptance

Install `warehouse_agents/requirements.txt` plus `pytest`, `pytest-asyncio` in a dedicated environment. The existing isolated validation environment is `data/models/warehouse-agent-runtime/venv`.

```sh
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python -m pytest tests/warehouse_agents -q
python -m warehouse_agents.check_runtime
```

The live checker uses real Bedrock calls (and incurs provider charges). It exercises MCP discovery and structured output, trained scoring, drift, deterministic repeat at one cutoff, future-cutoff rejection and **MCP -> Analyst LLM -> A2A Operations LLM -> tools -> answer**. It saves evidence at `data/models/warehouse-agent-validation/live_acceptance.json`. Set `WAREHOUSE_AGENT_TOKEN` in the checker environment when authentication is enabled.

For real PostgreSQL integration, provide a disposable database **named `warehouse_test`** via `WAREHOUSE_AGENT_TEST_DSN`. Tests refuse any other database name, then drop/recreate only its `dw`, `mart`, `meta`, `staging` schemas. **Never point this variable at your application database.** Example:

```sh
docker run --name coinsight-warehouse-agent-test-db \
  -e POSTGRES_PASSWORD=warehouse_test_only -e POSTGRES_DB=warehouse_test \
  -p 127.0.0.1:15439:5432 -d postgres:16
# Wait until pg_isready reports ready, then:
WAREHOUSE_AGENT_TEST_DSN=postgresql://postgres:warehouse_test_only@127.0.0.1:15439/warehouse_test \
  OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python -m pytest tests/warehouse_agents -q
docker rm -f coinsight-warehouse-agent-test-db
```

Integration covers actual schema SQL, a known missing hour, failed quality evidence, load reconciliation, stale-mart detection/refreshed parity and rejection of database writes. Unit tests cover causal feature prefixes/gaps, frozen-score reproducibility, artifact checksum, report accounting, tool allowlists/schema bounds, loop budgets, sanitized errors, request authentication/rate/body bounds, source validation and task retention. See [VALIDATION.md](VALIDATION.md) for the completed run and remaining deployment constraints.

## Troubleshooting / rollback

```sh
docker compose --env-file .env -f warehouse_agents/compose.yml logs --tail 100 analyst operations warehouse-mcp
```

Bedrock unavailable: verify model access, region, credentials and provider capacity; failed tasks are explicit. Warehouse unavailable: verify observer URL, network, schema 005 and SELECT grants. Airflow 401/403: supply a valid Airflow 3 API token. Forecast unavailable: verify the existing service on localhost 8011. Source rejection: inspect UTC cutoff, contiguous closed candles and machine clock; do not bypass validation to force a forecast.

To roll back, stop this compose project and restore its prior image and matching trusted model directory. It uses separate ports/network and does not replace the existing forecast services.

## Web Desk commands

The web Desk exposes `@trade` (internal Analyst) and `@sre` (internal Operations), plus `/predict BTC|ETH` and local `/tools`. `/anomaly` and the legacy `/drift`/`model_health` path are production-disabled while their offline implementations remain in the repository. The API proxies validated commands to `/desk/command` on this gateway; no provider keys reach the browser. Plain text keeps the legacy Desk path. Public A2A cards are named Trade/SRE; internal roles and service IDs stay compatible. See the served `/docs/desk-commands` and `/docs/code-guide` for the walkthrough and contracts.
