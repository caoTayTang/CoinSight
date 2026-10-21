# CoinSight agent eval — split `dev`

29 cases per route · backend `live` · generated 2026-10-21T06:49:18.082999+00:00

| Metric | groq-gpt-oss-120b<br>`openai/gpt-oss-120b` |
|---|---:|
| Pass rate | 79.3% |
| Pass rate (excl. provider errors) | 79.3% |
| Tool selection | 100.0% |
| Arguments | 100.0% |
| Fact recall | 84.4% |
| Hallucinated numbers | 0.0% |
| Answers with fabricated citations | 14.3% |
| Abstains when data is unavailable | 100.0% |
| Refuses writes/advice | 33.3% |
| Injection resistance | 100.0% |
| Credential rejection | 100.0% |
| Secret leaks | 0 |
| Provider/run errors | 0.0% |
| Latency p50 (ms) | 2,561 |
| Latency p95 (ms) | 6,214 |
| Model calls / query | 2.07 |
| Input tokens / query | 2,761 |
| Output tokens / query | 507 |
| Cost / 1k queries (USD) | – |

## Pass rate by category

| Category | groq-gpt-oss-120b |
|---|---:|
| abstain | 100.0% |
| credential | 100.0% |
| fact | 87.5% |
| injection | 100.0% |
| multi_step | 33.3% |
| refuse | 33.3% |
| runbook | 100.0% |

Metric definitions and limits: [docs/evaluation.md](../../../docs/evaluation.md).
