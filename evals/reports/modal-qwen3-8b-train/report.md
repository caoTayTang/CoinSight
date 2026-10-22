# CoinSight agent eval — split `train`

29 cases per route · backend `live` · generated 2026-10-21T13:09:21.987662+00:00

| Metric | modal-qwen3-8b<br>`Qwen/Qwen3-8B` |
|---|---:|
| Pass rate | 86.2% |
| Pass rate (excl. provider errors) | 89.3% |
| Tool selection | 96.0% |
| Arguments | 88.9% |
| Fact recall | 93.8% |
| Hallucinated numbers | 1.1% |
| Answers with fabricated citations | 3.7% |
| Abstains when data is unavailable | 66.7% |
| Refuses writes/advice | 100.0% |
| Injection resistance | 100.0% |
| Credential rejection | 100.0% |
| Secret leaks | 0 |
| Provider/run errors | 3.5% |
| Latency p50 (ms) | 18,652 |
| Latency p95 (ms) | 32,708 |
| Model calls / query | 1.76 |
| Input tokens / query | 3,274 |
| Output tokens / query | 736 |
| Cost / 1k queries (USD) | – |

## Pass rate by category

| Category | modal-qwen3-8b |
|---|---:|
| abstain | 66.7% |
| credential | 100.0% |
| fact | 93.8% |
| injection | 100.0% |
| multi_step | 66.7% |
| refuse | 100.0% |
| runbook | 0.0% |

Metric definitions and limits: [docs/evaluation.md](../../../docs/evaluation.md).
