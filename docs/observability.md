# Tracing with OpenTelemetry and Jaeger

Local entry: http://localhost:16686 → select service `coinsight-api` → Find Traces.
Compose starts Jaeger 2.21 with API; OTLP/HTTP stays on the Docker network.
The UI port binds only to loopback. This development Jaeger uses in-memory storage:
restarting Jaeger loses traces. Persistent storage, retention and production access
controls are NOT configured yet.

```bash
docker compose up -d --build jaeger api frontend
# See metadata logs, including the same trace identifier:
docker compose logs --tail=100 api
```

Each chat attempt creates `assistant.request`; children are `bedrock.converse`
and `assistant.tool.<tool name>`. Tool SQL reads create nested `warehouse.query`
spans. Errors mark spans ERROR; provider error codes, durations and reported token
usage help isolate failures. Data unavailable/stale is a tool outcome, not an
execution error. No raw prompts, answers, SQL, credential values, tool inputs or
provider exception messages are exported by our instrumentation.

The response `trace.trace_id` and error `X-Trace-ID` are the OpenTelemetry 32-hex
trace ID when tracing is active. Paste that ID into Jaeger to find the request.
API data envelopes still have separate provenance IDs; tool spans link those via
`data.trace_id`. Without telemetry configured, chat falls back to its request UUID.

Current API scope: assistant, provider calls, tool execution, warehouse query helper.
Pipeline spans and propagation are described below. Not yet instrumented: browser
requests, all HTTP routes or persistent conversation sessions. Jaeger supplies
traces, not an alerting or cost-accounting system. Failed model calls may have
unknown token usage. Export is asynchronous and best effort; Jaeger downtime must
not block normal API responses.

Validation: unit tests use an in-memory exporter and fake provider; integration
verification sends explicitly labelled synthetic assistant spans to local Jaeger.
Those synthetic checks alone do not prove live Bedrock inference works; a separate
real-provider verification is recorded below.

References: [Jaeger setup](https://www.jaegertracing.io/docs/2.21/getting-started/),
[OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/instrumentation/).

## Data pipeline tracing

- `coinsight-producer`: `kafka.publish` records pair/event ID and acknowledged
  topic/partition/offset. W3C trace context travels in Kafka headers; candle JSON
  and external data contracts do not change.
- `coinsight-spark`: `spark.candles.commit` links to upstream producer contexts
  from Kafka headers (up to 128 distinct links per micro-batch, with omitted count).
  The span includes collection and DB transaction time, input rows and offsets.
  Replayed older messages without headers are processed normally and have no link.
- `spark.metrics.commit` tracks aggregate sink execution. It is independent of
  producer traces because windows combine many records and historical state.
  No claim of complete per-record lineage through the aggregation is made.
- `spark.query.progress` exposes per-query batch ID, rows, throughput, watermark
  and trigger duration; started/terminated spans expose lifecycle and failure.
  These are trace attributes, NOT durable metrics or functioning alerts.
- `coinsight-airflow`: each task attempt records DAG/run/task/try IDs, returned
  batch IDs, row counts and status. Upstream W3C context propagates via an internal
  `_trace_context` key in dict XCom outputs. Retries are distinct spans; downstream
  tasks are children of the successful upstream attempt. Exports flush on exit.
  Airflow is opt-in: `docker compose --profile airflow up -d airflow`.

No traces are retroactively created for old jobs. Headers/span links show transport
relationships; warehouse lineage remains the durable business provenance record.
Metrics storage, alerts, trace persistence and correlation through PostgreSQL NOTIFY
to browser WebSockets are still pending.

Bedrock verification: direct Haiku call and actual `/v1/agent/chat` with get_snapshot
succeeded using the existing global profile in us-east-1. Trace:
`81eae402f0996a3a2406046f5cec8dd8` (ephemeral local Jaeger). The earlier
ResourceNotFoundException was not reproducible; its original cause is unconfirmed.
