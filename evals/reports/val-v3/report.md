# CoinSight agent eval — split `val`

28 cases per route · backend `live` · generated 2026-10-21T18:05:12.959574+00:00

| Metric | groq-gpt-oss-120b<br>`openai/gpt-oss-120b` |
|---|---:|
| Pass rate | 92.9% |
| Pass rate (excl. provider errors) | 92.9% |
| Tool selection | 100.0% |
| Arguments | 100.0% |
| Fact recall | 100.0% |
| Hallucinated numbers | 1.5% |
| Answers with fabricated citations | 0.0% |
| Abstains when data is unavailable | 100.0% |
| Refuses writes/advice | 100.0% |
| Injection resistance | 100.0% |
| Credential rejection | 100.0% |
| Secret leaks | 0 |
| Provider/run errors | 0.0% |
| Latency p50 (ms) | 2,950 |
| Latency p95 (ms) | 8,861 |
| Model calls / query | 2.14 |
| Input tokens / query | 4,399 |
| Output tokens / query | 563 |
| Cost / 1k queries (USD) | – |

## Pass rate by category

| Category | groq-gpt-oss-120b |
|---|---:|
| abstain | 100.0% |
| credential | 100.0% |
| fact | 100.0% |
| injection | 100.0% |
| multi_step | 66.7% |
| refuse | 100.0% |
| skill | 0.0% |

Metric definitions and limits: [docs/evaluation.md](../../../docs/evaluation.md).
