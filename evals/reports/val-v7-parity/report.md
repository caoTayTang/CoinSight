# CoinSight agent eval — split `val`

3 cases per route · backend `live` · generated 2026-10-24T15:53:19.252388+00:00

| Metric | groq-gpt-oss-120b<br>`openai/gpt-oss-120b` |
|---|---:|
| Pass rate | 100.0% |
| Pass rate (excl. provider errors) | 100.0% |
| Tool selection | 100.0% |
| Arguments | – |
| Fact recall | 100.0% |
| Hallucinated numbers | 0.0% |
| Answers with fabricated citations | 0.0% |
| Abstains when data is unavailable | – |
| Refuses writes/advice | – |
| Injection resistance | – |
| Credential rejection | – |
| Secret leaks | 0 |
| Provider/run errors | 0.0% |
| Latency p50 (ms) | 3,024 |
| Latency p95 (ms) | 3,515 |
| Model calls / query | 2 |
| Input tokens / query | 4,892 |
| Output tokens / query | 444 |
| Cost / 1k queries (USD) | – |

## Pass rate by category

| Category | groq-gpt-oss-120b |
|---|---:|
| fact | 100.0% |

Metric definitions and limits: [docs/evaluation.md](../../../docs/evaluation.md).
