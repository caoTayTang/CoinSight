# CoinSight agent eval — split `test`

28 cases per route · backend `live` · generated 2026-10-21T13:18:12.973817+00:00

| Metric | modal-qwen3-8b<br>`Qwen/Qwen3-8B` |
|---|---:|
| Pass rate | 92.9% |
| Pass rate (excl. provider errors) | 92.9% |
| Tool selection | 87.5% |
| Arguments | 100.0% |
| Fact recall | 100.0% |
| Hallucinated numbers | 12.8% |
| Answers with fabricated citations | 0.0% |
| Abstains when data is unavailable | 100.0% |
| Refuses writes/advice | 66.7% |
| Injection resistance | 100.0% |
| Credential rejection | 100.0% |
| Secret leaks | 0 |
| Provider/run errors | 0.0% |
| Latency p50 (ms) | 17,029 |
| Latency p95 (ms) | 40,566 |
| Model calls / query | 1.71 |
| Input tokens / query | 3,136 |
| Output tokens / query | 752 |
| Cost / 1k queries (USD) | – |

## Pass rate by category

| Category | modal-qwen3-8b |
|---|---:|
| abstain | 100.0% |
| credential | 100.0% |
| fact | 100.0% |
| injection | 100.0% |
| multi_step | 66.7% |
| refuse | 66.7% |
| runbook | 100.0% |

Metric definitions and limits: [docs/evaluation.md](../../../docs/evaluation.md).
