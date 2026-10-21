# Service unreachable / container down / dịch vụ không truy cập được

An HTTP timeout or connection refusal proves a service endpoint is unreachable from the probing agent. It does not prove the container is stopped: DNS, network, a wrong URL, or an unhealthy process can produce the same symptom.

Use service_health to observe configured endpoints and timestamps. Use warehouse_coverage to check whether closed-hour data is still arriving. Use airflow_status for scheduler evidence where configured. Compare observations before suggesting a cause.

An operator can inspect docker compose ps and docker compose logs --tail 100 for the affected service. These are operator actions; the SRE agent has no Docker socket and cannot restart containers. Do not expose environment variables or credentials in logs. Restart or recovery requires human review of the affected service and dependencies.

If service_health returns HTTP 503 report that status. If connection fails report unreachable, not confirmed container down. If the endpoint is reachable report HTTP reachability, not end-to-end warehouse health.
