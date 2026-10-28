# Validation record — 2026-10-19

**Status: local services, deterministic acceptance and the full real-LLM A2A acceptance pass with Amazon Nova 2 Lite (`us.amazon.nova-2-lite-v1:0`). This is not a public-production certification.**

## Completed

- **27 tests passed**, including real PostgreSQL schema integration and real HTTP/A2A delegation with an explicitly scripted LLM. Full suite ran in 2.12 seconds with BLAS threads capped. No application warehouse schemas were modified: integration used a separate disposable database named `warehouse_test` on localhost 15439.
- Causal features match prefixes; changing future rows does not change earlier features. A missing hour invalidates the affected feature window.
- Frozen model reload/scoring, cutoff/threshold rule, model-binary corruption rejection, JSON checksum verification and test-report reconciliation pass.
- Source mocks exercise missing/wrong-count hours, unclosed klines, invalid prices, clock disagreement, timezone-naive/future cutoffs and valid contiguous input.
- Actual A2A discovery/JSON-RPC/task/artifact flow passes over real HTTP: Analyst -> Operations, separate task IDs, structured evidence, authentication and invalid request failure. The LLM is scripted in this integration test; this is not claimed as real Bedrock success.
- Tool allowlist, schema bounds/extra-field rejection, loop budget, redaction of sensitive tool exceptions, bearer auth, request size/rate limits and task TTL/capacity pass.
- Coverage source contract is checked against the real archive writer (`binance`), preventing a wrong source filter from fabricating missing hours.
- PostgreSQL checks detect one intentionally missing closed hour, a failed persisted quality check and a stale mart. Refresh resolves mart parity. Staging/rejection/duplicate/accepted accounting balances. Transactions reject writes.
- Historical validation covered trained-anomaly/model-health responses. Those legacy paths are now production-disabled; current MCP acceptance covers forecast and agent delegation instead.
- All three new containers started healthy on localhost 8020/8021/8022. Existing parent services remained on 8010/8011/8012.
- Runtime dependency `pip check` passed. Compose validation passed. Direct dependencies and resolved container lock are recorded.

## Frozen experiment

Training: 17,375 rows (2023–2024 detection cutoffs). Calibration: 8,760 rows (2025). Retrospective test: 6,984 aligned 2026 timestamps. No training labels or 2026 tuning.

| Detector | Alerts | Rate |
|---|---:|---:|
| Isolation Forest | 78 | 1.1168% |
| Fixed MAD | 101 | 1.4462% |

These are alert rates, **not accuracy or false-positive rates**. No labeled anomaly precision/recall is established. Frozen threshold: `0.6055684921806122`.

Model SHA-256: `4828a1ecb11d2913a931d59530ca5d7634af27c8769b62a5f98295c41eeafde6`.

## Provider issue and verified resolution

The existing Bedrock configuration initially answered a simple probe. Subsequent live acceptance returned `ServiceUnavailableException` / “Bedrock is unable to process your request.” Reproduced with plain “Reply OK” as well as 32/256/1100-token requests, a minimal tool schema and the full reasoning request. Therefore **MCP -> real Analyst LLM -> real Operations LLM -> final answer has not passed**. The server fails the task explicitly; it does not invent a model answer or silently use a scripted backend.

Resolution: switched only this extension to Amazon Nova 2 Lite, recreated all three containers with the current `.env` key, and verified key equality without logging it. The full live checker passed: MCP -> real Analyst LLM -> A2A Operations LLM -> `warehouse_coverage` + `airflow_status` -> final answer. The main application model setting was not changed. The earlier Haiku failure is historical, not the current Nova acceptance status.

Bounded standard retries and provider deadlines are configured. Re-run `python -m warehouse_agents.check_runtime` after provider access recovers. Its default mode now passes with Nova 2 Lite. `--market-only` validates trained scoring/MCP only and explicitly records that live reasoning was skipped.

Application warehouse and Airflow services were not running during live checks. Their unavailable states are expected; real queries were validated against the disposable schema, not presented as observations of the live warehouse. Airflow authentication/network connection must be configured for actual DAG evidence.

## Evidence and reproduction

Local ignored artifacts:

- `data/models/warehouse-anomaly/v1/`: sealed plan/model/report, binary, individual test scores and frozen source copies.
- `data/models/warehouse-agent-validation/tests.xml`: JUnit test results.
- `data/models/warehouse-agent-validation/live_tools.json`: actual anomaly, drift and forecast responses.
- `data/models/warehouse-agent-validation/market_acceptance.json`: deployed MCP acceptance without LLM; skipped status is explicit.
- `data/models/warehouse-agent-validation/live_acceptance.json`: full live attempt; records real LLM acceptance as passed with Nova 2 Lite, including peer task IDs and tool evidence.
- `data/models/warehouse-agent-validation/provider_status.json`: sanitized provider failure record.

See [README.md](README.md) for deployment, dependencies, database role, live acceptance, rollback and troubleshooting. The tests and live checker are checked-in source; model/data/result artifacts are intentionally local and must be distributed separately with verified checksums.

## Deployment acceptance still required

For this laptop: the default live checker has passed with Nova 2 Lite; connect the observer account/Airflow token if operational evidence is needed. For public or multi-user production: authenticated TLS/identity, least-privilege credentials, durable audit/task storage, monitoring/SLOs and a controlled rollout remain deployment work. Local health endpoints alone do not certify those properties.

## Multi-provider router extension

Bedrock/Groq/OpenRouter failover is implemented and connected to both reasoning agents. The default Nova bearer route passed the real MCP/A2A checker after routing was enabled. Groq/OpenRouter adapters were tested with mocked provider responses; live acceptance awaits user-supplied keys. The router test run recorded 50 passing tests and three PostgreSQL integration skips (the earlier 27-test run included those real database tests). See `router_tests.xml` for the router-era suite and [ROUTER.md](ROUTER.md) for key/model setup, data disclosure across configured providers, deadlines and cooldown.

Live failover was also verified against AWS: an intentionally invalid model returned HTTP 400, then the router selected Nova 2 Lite successfully. Sanitized proof: `data/models/warehouse-agent-validation/live_router_failover.json`. No production route was changed for that probe.

## Round-robin deployment

Configured `strategy: round_robin` with Groq GPT-OSS 120B -> OpenRouter Gemma 4 31B Free -> Bedrock Haiku 4.5 -> Nova 2 Lite. Latest suite: **54 passed, 3 PostgreSQL integration skips**. Tests cover rotation, missing keys, cooldown, concurrent reservation and 429 fallback.

Real full MCP/A2A acceptance passed after deployment. Both agents selected Groq successfully on their first model call, then attempted Gemma on the second call; OpenRouter returned HTTP 429, and Haiku completed successfully with HTTP 200. Haiku's earlier 503 is no longer reproduced in this run. OpenRouter inference success remains unverified while rate-limited. Sanitized routing proof: `data/models/warehouse-agent-validation/round_robin_routing.json`; full checker log: `round_robin_live.log`.

Rotation is per process and per LLM call, with independent Analyst/Operations state. It spreads calls but does not increase shared account quotas or impose a global RPM cap.

## Docs and web Desk integration

Public names are Trade (`analyst` role) and SRE (`operations` role). Desk commands `@trade`, `@sre` and `/predict BTC|ETH` are wired through `/v1/agent/command`; `/anomaly` and legacy `/drift` are production-disabled, while `/tools` is local help. Plain text keeps the legacy Bedrock Desk path. Provider keys stay server-side.

Validation: 59 agent/bridge tests passed with 3 PostgreSQL integration skips; 16 frontend tests passed; 6 API proxy tests passed inside the API image. All five server-backed commands passed through the actual `localhost:3000/api` endpoint. Direct tools reported zero LLM calls; Trade/SRE returned real A2A task IDs, routing and evidence. SRE successfully read `warehouse_coverage` from the configured live database. Proof is in `data/models/warehouse-agent-validation/desk_live.json`.

The frontend/docs image was rebuilt and served on port 3000. Seven docs URLs returned HTTP 200, the deployed JS contained the six new guides and landing view, and 32 internal guide links were checked. No enabled browser surface was available for visual interaction QA; build, semantic/parser tests, HTTP routing and real backend actions were verified.

## Response rendering and guardrails

Desk responses now use a dedicated Markdown renderer with safe links, no raw HTML/remote images, copyable code, bounded tables and guarded Mermaid. Numeric visuals are built only from known tool evidence (anomaly score/threshold, feature PSI, reference vs predicted close, warehouse coverage), never model-written chart points. Mermaid is schematic, size/type bounded, strict-mode and sanitized with DOMPurify; source remains visible on render failure.

Backend guards reject credential-like inputs, redact configured/recognized credentials in answers, attach evidence availability metadata, and replace a model conclusion when all called tools lacked usable evidence. Delegation wrappers cannot hide missing leaf observations. A model argument error is never executed; sanitized allowed-key guidance permits a corrected retry within the existing loop budget. These controls do not prove arbitrary model prose true or solve every prompt injection.

Tests: 65 agent/guardrail tests passed (3 PostgreSQL integration skips), 24 frontend tests passed, 8 API proxy/credential tests passed. Real component SSR checks covered Markdown tables/code, source-derived charts and blocked links/HTML/images; the actual Mermaid parser accepted valid diagrams and rejected invalid syntax. Real port-3000 checks confirmed secret rejection without input echo and response guardrail metadata. A live Trade attempt with an unadvertised symbol argument was blocked and honestly marked unavailable; schema-repair guidance was then added and tested. No browser surface was enabled for visual interaction QA.

Source walkthrough is served at `/docs/response-guardrails`; latest real responses are saved in `data/models/warehouse-agent-validation/response_live.json`.

After the schema guidance update, the final port-3000 live run returned available evidence for anomaly, drift, Trade and SRE. Trade/SRE each used two real LLM calls. The published response/guardrail guide was verified in the deployed docs bundle.
