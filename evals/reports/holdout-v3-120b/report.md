# CoinSight agent eval — split `holdout`

12 cases per route · backend `live` · generated 2026-10-21T17:36:35.043330+00:00

| Metric | groq-gpt-oss-120b<br>`openai/gpt-oss-120b` |
|---|---:|
| Pass rate | 91.7% |
| Pass rate (excl. provider errors) | 91.7% |
| Tool selection | 100.0% |
| Arguments | 100.0% |
| Fact recall | 100.0% |
| Hallucinated numbers | 1.1% |
| Answers with fabricated citations | 0.0% |
| Abstains when data is unavailable | 100.0% |
| Refuses writes/advice | 100.0% |
| Injection resistance | 100.0% |
| Credential rejection | – |
| Secret leaks | 0 |
| Provider/run errors | 0.0% |
| Latency p50 (ms) | 3,357 |
| Latency p95 (ms) | 5,014 |
| Model calls / query | 2.17 |
| Input tokens / query | 4,132 |
| Output tokens / query | 579 |
| Cost / 1k queries (USD) | – |

## Pass rate by category

| Category | groq-gpt-oss-120b |
|---|---:|
| abstain | 100.0% |
| fact | 100.0% |
| injection | 100.0% |
| multi_step | 100.0% |
| refuse | 100.0% |
| skill | 0.0% |

Metric definitions and limits: [docs/evaluation.md](../../../docs/evaluation.md).
