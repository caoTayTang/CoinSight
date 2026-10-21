---
name: service-unreachable
description: A service seems down, slow or unreachable (API, forecast, Airflow, Kafka, Spark, Postgres, "dịch vụ không truy cập được"), or a request failed. Use to say what is observed versus what is only suspected.
---
# Service unreachable or failing

## Steps
1. `service_health`: each component's probe, status, latency and the time observed.
2. For data freshness, `warehouse_coverage` and the stream freshness in `service_health`: is data still arriving?
3. For a failed or slow request, `search_traces` then `inspect_trace`. A trace ID given by the user can be
   inspected directly.

## How to report
- A table: component, status, evidence (HTTP code, latency, age of latest data).
- Then "Observed" (facts from tools) and "Possible causes" (clearly labelled as suspicion).
- Then the operator's next step, e.g. `docker compose ps` and `docker compose logs --tail 100 <service>`.

## Boundaries
- Connection refused or a timeout proves the endpoint is unreachable from the agent, not that the container stopped:
  DNS, network, a wrong URL or a hung process look the same.
- Reachable means reachable, not that the whole pipeline is healthy. Empty traces don't prove health.
- You have no Docker socket and can't restart anything. Never print environment variables or credentials.
