---
name: service-unreachable
description: Checks whether CoinSight services (API, forecast, Airflow, Kafka, Postgres, Spark stream, Jaeger) are up, and investigates failed or slow requests with traces. Use when something seems down, slow or unreachable, a request failed, or the user asks "dịch vụ không truy cập được".
---

# Service unreachable

## What `service_health` returns

`checks[]`, one per component, each with `status` and evidence:

| Component | How it is probed | `ok` means |
|---|---|---|
| `warehouse_api` | HTTP `/health` | 2xx |
| `forecast` | HTTP `/health` | 2xx |
| `traces` | Jaeger UI | 2xx |
| `airflow` | `/api/v2/monitor/health` | every part (metadatabase, scheduler, ...) is `healthy` |
| `kafka` | Kafka UI clusters API | every cluster `ONLINE` with brokers |
| `postgres` | `select 1` | query returned |
| `stream` | age of the newest live candle and stream metric per symbol | every `age_seconds` ≤ `stale_after_seconds` (300) |

| Status | Meaning |
|---|---|
| `ok` | Reachable and its own check passed |
| `degraded` | Reachable but non-2xx (`http_status`), or a part unhealthy (`detail`), or stream output stale |
| `unreachable` | Connection failed or timed out (`error_type`). The agent can't reach it; the container may still be running. |
| `unknown` | The probe itself failed |

`search_traces(service, lookback_minutes)` lists recent traces with duration and error flags. `inspect_trace(trace_id)` returns the spans of one trace.

## Workflow

If the user asks you to restart or fix a service, open the answer by saying you can't: you have no Docker access and are read-only. Then investigate and report as below.

```
- [ ] 1. service_health. If the user mentions missing data, also warehouse_coverage in the same step.
- [ ] 2. For a failed or slow request: search_traces for the service, then inspect_trace on the slowest or failed one.
        A trace ID from the user goes straight to inspect_trace.
```

## Reading the result

| Observation | Possible causes (suspicion, not fact) | Operator check |
|---|---|---|
| `unreachable`, `error_type` ConnectError | Container stopped, wrong URL, network | `docker compose ps <service>` |
| `unreachable`, timeout | Hung process, overloaded host | `docker compose logs --tail 100 <service>` |
| `degraded` with `http_status` 5xx | Service up, failing internally | logs of that service |
| `stream` degraded, Kafka ok | Spark job stopped or stuck | `docker compose logs --tail 100 spark` |
| `stream` degraded, Kafka degraded | Upstream: broker or producer | Kafka first |
| Everything `ok` but the user saw an error | Transient, or a path the probes don't cover | the trace of that request |

## Report

```markdown
**<n> of <total> components are not ok: <names>.** Observed <observed time> UTC.

| Component | Status | Evidence |
|---|---|---|
| <component> | <status> | <http_status / latency_ms / age_seconds / error_type> |

Observed: <facts from the tools only>.
Possible causes: <labelled as suspicion>.
Next step: <operator command from the table>.

[skill:service-unreachable]
```

## Gotchas

- Reachable means reachable. It doesn't prove the pipeline is healthy; check stream freshness.
- Empty trace results don't prove health. They may mean no traffic or no tracing.
- You have no Docker socket and can't restart anything. Never print environment variables, URLs with tokens, or credentials.

Every figure in the answer comes from a tool result in this conversation. Placeholders in <angle brackets> show where a tool value goes; never fill them with example or estimated numbers, and say "not checked" instead.
