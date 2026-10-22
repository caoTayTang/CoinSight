# CoinSight agent eval — split `val`

28 cases per route · backend `live` · generated 2026-10-21T07:31:53.512926+00:00

| Metric | groq-gpt-oss-120b<br>`openai/gpt-oss-120b` |
|---|---:|
| Pass rate | 96.4% |
| Pass rate (excl. provider errors) | 96.4% |
| Tool selection | 95.8% |
| Arguments | 100.0% |
| Fact recall | 100.0% |
| Hallucinated numbers | 0.0% |
| Answers with fabricated citations | 0.0% |
| Abstains when data is unavailable | 100.0% |
| Refuses writes/advice | 100.0% |
| Injection resistance | 50.0% |
| Credential rejection | 100.0% |
| Secret leaks | 0 |
| Provider/run errors | 0.0% |
| Latency p50 (ms) | 2,967 |
| Latency p95 (ms) | 4,790 |
| Model calls / query | 2.07 |
| Input tokens / query | 2,956 |
| Output tokens / query | 438 |
| Cost / 1k queries (USD) | – |

## Pass rate by category

| Category | groq-gpt-oss-120b |
|---|---:|
| abstain | 100.0% |
| credential | 100.0% |
| fact | 100.0% |
| injection | 50.0% |
| multi_step | 100.0% |
| refuse | 100.0% |
| runbook | 100.0% |

Metric definitions and limits: [docs/evaluation.md](../../../docs/evaluation.md).
