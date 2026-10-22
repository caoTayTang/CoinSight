# CoinSight agent eval — split `test`

12 cases per route · backend `live` · generated 2026-10-21T17:35:15.544107+00:00

| Metric | groq-gpt-oss-20b<br>`openai/gpt-oss-20b` |
|---|---:|
| Pass rate | 100.0% |
| Pass rate (excl. provider errors) | 100.0% |
| Tool selection | 100.0% |
| Arguments | 100.0% |
| Fact recall | 100.0% |
| Hallucinated numbers | 0.0% |
| Answers with fabricated citations | 0.0% |
| Abstains when data is unavailable | 100.0% |
| Refuses writes/advice | 100.0% |
| Injection resistance | 100.0% |
| Credential rejection | – |
| Secret leaks | 0 |
| Provider/run errors | 0.0% |
| Latency p50 (ms) | 2,923 |
| Latency p95 (ms) | 4,939 |
| Model calls / query | 2.33 |
| Input tokens / query | 4,482 |
| Output tokens / query | 489 |
| Cost / 1k queries (USD) | – |

## Pass rate by category

| Category | groq-gpt-oss-20b |
|---|---:|
| abstain | 100.0% |
| fact | 100.0% |
| injection | 100.0% |
| multi_step | 100.0% |
| refuse | 100.0% |
| skill | 100.0% |

Metric definitions and limits: [docs/evaluation.md](../../../docs/evaluation.md).
