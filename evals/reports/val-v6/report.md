# CoinSight agent eval — split `val`

32 cases per route · backend `live` · generated 2026-10-24T10:40:14.599208+00:00

| Metric | groq-gpt-oss-120b<br>`openai/gpt-oss-120b` |
|---|---:|
| Pass rate | 87.5% |
| Pass rate (excl. provider errors) | 87.5% |
| Tool selection | 92.3% |
| Arguments | 100.0% |
| Fact recall | 81.0% |
| Hallucinated numbers | 0.0% |
| Answers with fabricated citations | 0.0% |
| Abstains when data is unavailable | 100.0% |
| Refuses writes/advice | 100.0% |
| Injection resistance | 100.0% |
| Credential rejection | 100.0% |
| Secret leaks | 0 |
| Provider/run errors | 0.0% |
| Latency p50 (ms) | 3,540 |
| Latency p95 (ms) | 6,589 |
| Model calls / query | 1.91 |
| Input tokens / query | 4,769 |
| Output tokens / query | 417 |
| Cost / 1k queries (USD) | – |

## Pass rate by category

| Category | groq-gpt-oss-120b |
|---|---:|
| abstain | 100.0% |
| clarify | 100.0% |
| credential | 100.0% |
| fact | 85.7% |
| injection | 100.0% |
| multi_step | 33.3% |
| refuse | 100.0% |
| skill | 100.0% |

Metric definitions and limits: [docs/evaluation.md](../../../docs/evaluation.md).
