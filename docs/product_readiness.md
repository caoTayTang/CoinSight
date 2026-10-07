# CoinSight — product critique, readiness and delivery backlog

Status: research prototype; NOT a completed DSS or production-ready service.
Build success, Docker startup and HTTP 200 only establish that specific technical
paths work. They do not establish usefulness, model validity or operational reliability.
Do not report a completion percentage without an agreed scope and evidence.

## Product decision

Primary user: someone reviewing tracked Spot markets and deciding which asset
needs further investigation. First workflow: select asset → observe recent movement
→ check freshness/completeness → inspect historical context → assess whether a
validated prediction is available → inspect supporting evidence.
No buy/sell recommendation or automatic execution is implemented.

Market workspace explains observations and limitations. Data & model operations
exposes provenance, coverage and evaluation. These are navigation contexts, NOT
security roles. Authentication and authorization are not implemented by this split.

## Critical review grounded in current code

- `frontend/src/App.jsx`: technical batch IDs occupied primary user metrics;
  “Refresh batch” only re-fetches API data and does not schedule ingestion.
- `frontend/src/useLiveStream.js`: socket-open is transport status, not proof of
  fresh/complete candles. Its clock previously advanced only on server messages;
  a silent connection could leave stale data looking fresh.
- `app/api.py`: summary freshness and availability do not prove full 15-minute
  coverage. Seven-day aggregate event count is not proof of seven complete days.
- `app/chat_agent.py`: tools restrict symbols to BTC/ETH/SOL while the asset list
  includes other symbols. Each request starts a new conversation; displayed chat
  history is not conversational memory. Responses expose tool names, but the UI
  does not yet provide per-claim evidence citations.
- Bedrock previously failed with ResourceNotFoundException. A subsequent direct
  inference and real tool-backed API response succeeded with the same model ID.
  Original cause remains unknown; one success does not establish reliability.
- `pipeline/decision/direction_model.py`: logistic regression, chronological split,
  scaling within a pipeline, baseline comparison and publication gates exist.
  This is useful infrastructure, not evidence of stable predictive skill.
- The test set is used as a publication gate. Repeated candidates evaluated on
  that set make it part of selection; require a later untouched evaluation period.
  Audit validation labels at the test boundary: fit boundaries are purged, but the
  validation slice reaches the day immediately before test_start.
- Artifact version is based on feature version and cutoff date; registry rows are
  upserted. Review whether retraining can overwrite the identity of historical
  predictions. Artifact bytes and DB registration are not one atomic operation.
- Prediction lineage records row.batch_id. Verify whether it captures every batch
  contributing to rolling daily/hourly features, not merely the latest batch.
- Frontend CSS contains accumulated overrides from redesigns. Consolidate tokens,
  component ownership and breakpoint rules before further large layout changes.
- User workflow, usability and decision value have not been evaluated with users.
  UI screenshots and smoke tests cannot establish those outcomes.

## Delivery order and acceptance criteria

### P0 — truthful product and first usable decision workflow

- [x] Publish this critical review and stop equating technical smoke tests with readiness.
- [x] Introduce distinct market/operations navigation with no claim of role security.
- [x] Default to a plain-language overview of observed movement, coverage and prediction availability.
- [x] Label transport connectivity separately from freshness and completeness.
- [x] Use a local clock to age observations when server messages stop.
- [x] Rename refresh action to explain that it reloads data, not ingestion.
- [x] Remove batch ID from the main market metrics; retain it in operations.
- [ ] Demonstrate a complete user task with at least two new users; record points
  of confusion and whether users can explain the data date and model limitation.
- [ ] Fix Bedrock inference and test one successful tool-backed response, unsupported
  asset handling and provider failure. Passing requires visible supporting evidence.
- [ ] Align asset capabilities across UI/API/model/chat; publish capabilities from API
  so frontend does not duplicate the BTC/ETH/SOL support list.

### P1 — defensible DSS

- [ ] Agree the review/prioritization decision and success measure with Duong and rubric.
- [ ] Define reproducible observation rules with explicit horizon, thresholds and
  reasons. Missing/stale data must suppress conclusions; label rules as rules.
- [ ] Compare assets over identical periods with completeness disclosed; verify
  outcomes against SQL fixtures and do not rank incomparable windows.
- [ ] Audit split boundaries, label timing and rolling feature availability; add
  leakage tests. Record train/validation/test dates and sample counts in UI.
- [ ] Evaluate across rolling chronological windows, per asset and market regime;
  compare with documented baselines. Keep a truly untouched final evaluation.
- [ ] Show calibration, uncertainty/sample size and limitations; never imply that
  a probability of increase is expected return or proven economic usefulness.
- [ ] Make model versions immutable and trace each prediction to its exact artifact,
  feature snapshot and all source batches. Verify retries and partial failures.

### P1 — trustworthy warehouse and stream

- [ ] Replay the same historical archive twice; verify natural-key uniqueness,
  row counts and audit records, retaining command output as evidence.
- [ ] Restart producer/Spark during ingestion and simulate an upstream outage;
  measure missing/duplicate minutes before and after recovery.
- [ ] Verify Airflow schedule, retries, failed tasks and backfills in the actual
  running environment; show timestamps rather than promised schedule as success.
- [ ] Expose expected vs observed distinct minutes and gaps for each aggregate;
  specify whether the window is complete, elapsed or still in progress.
- [ ] Trace a displayed price and prediction through human-readable lineage UI.

### P2 — deployment and operational readiness

- [ ] Authentication, authorization, rate limits and Bedrock budgets; test failures.
- [ ] Move conversation/provider calls off blocking API paths where necessary;
  define timeouts, concurrency limits, retries and cancellation behavior.
- [ ] Load-test WebSockets: current design creates a PostgreSQL listener per client.
  Establish connection limits and design shared fan-out if needed.
- [ ] Monitor lag, failed jobs, gaps and costs; demonstrate actionable alerts.
- [ ] Backup/restore exercise, secret rotation and documented rollback.
- [ ] Verify remote CI and actual deployment, HTTPS/origin/WS configuration.
- [ ] Consolidate frontend styling, keyboard/modal focus behavior and mobile layout.

## Evidence ledger

Previous local checks: Vite/Docker build and browser navigation at 1512px/390px.
These establish rendering/navigation only. They do not verify model quality,
continuous uptime, Bedrock inference, security, disaster recovery or usability.

First improvement pass: navigation/overview readiness rules covered by Node tests;
local browser checks cover market/operations navigation and layout. Record failures
explicitly; unexecuted checks remain unverified. Review this backlog after each phase.

## Assistant critique and backlog (user priority)

The present implementation is a bounded single-turn tool-calling assistant, not
an autonomous multi-agent platform. It has no skill registry, task planning,
conversation memory, tool-result verification or operational trace store.

- [x] Label the single-question limitation and supported assets in the UI.
- [x] Add request IDs, model/tool event timing, aggregated token usage, sanitized
  JSON request logs, and response details. This is basic request instrumentation.
- [ ] Persist/search traces with retention controls; dashboard for error rate,
  latency, tool success, token usage, budgets and provider failures.
- [ ] Correlate tool/API/data-source trace IDs and publish supporting citations;
  do not substitute model hidden reasoning for an audit trail.
- [ ] Define task skills with input/output contracts: market summary, comparison,
  quality diagnosis and model explanation. Each needs deterministic checks and evals.
- [ ] Add conversation context with explicit session scope, retention and reset;
  prevent selected-asset changes from silently mixing contexts.
- [ ] Measure groundedness, correct tool/asset selection, stale-data abstention,
  unsupported questions and recovery using a maintained evaluation dataset.
- [ ] Handle cancellation, provider timeouts, bounded retries, budget limits and
  safe tool errors; include tracing for every failure stage.
- [ ] Only introduce multi-agent delegation after demonstrating an independently
  measurable benefit over a single orchestrator with reliable tools.

### Jaeger implementation scope

OpenTelemetry → local Jaeger is implemented for assistant requests, model calls,
tools and warehouse query helper. See [observability.md](observability.md).
This adds trace search and parent/child timing; persistence, production retention,
alerts, pipeline-wide propagation and agent evaluations remain unchecked above.

Operational finding during Jaeger rollout: recreating API changed its container
address; frontend Nginx retained the old upstream resolution and returned 502.
Restarting frontend restored the proxy. TODO: configure runtime Docker DNS
resolution (with WebSocket support), and test API replacement without needing
frontend restart. This recovery was performed locally; resilience is not fixed.

## Required next work: alerts, memory, skills and evaluations

These are required backlog items, not optional polish and not completed by tracing.

- [ ] Pipeline alerts: measure freshness, missing-minute coverage, consumer lag,
  batch failure and task retries. Define owners, severity and recovery behavior.
  Acceptance: inject each failure locally; show firing and resolved alerts with
  links to the affected symbol/run/trace. Trace sampling must not hide alerts.
- [ ] Assistant alerts: monitor provider error rate, timeout rate, p95 latency,
  exhausted tool budget and token/cost budget. Acceptance: induced failures trigger
  an alert; redaction tests prevent prompt/credential disclosure.
- [ ] Session memory: bounded context, explicit asset scope, session isolation,
  clear/reset and retention. Acceptance: follow-up question resolves context,
  another session cannot access it, changing assets cannot silently reuse facts.
- [ ] Skill framework: typed input/output, required tools, validation and failure
  modes for market summary, equal-period comparison, quality diagnosis and model
  explanation. Acceptance: each skill has deterministic contract tests and
  end-to-end cases; missing/stale evidence blocks unsupported claims.
- [ ] Agent evaluations: versioned fixtures covering grounded numbers, wrong asset,
  stale/missing data, citation correctness, provider errors and prompt injection
  in tool content. CI reports regressions, latency, token use and failure cases;
  agree pass thresholds before claiming agent readiness.
