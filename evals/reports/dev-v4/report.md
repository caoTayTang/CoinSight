# CoinSight agent eval — split `dev`

29 cases per route · backend `live` · generated 2026-10-22T06:23:46.180930+00:00

| Metric | groq-gpt-oss-120b<br>`openai/gpt-oss-120b` |
|---|---:|
| Pass rate | 93.1% |
| Pass rate (excl. provider errors) | 93.1% |
| Tool selection | 100.0% |
| Arguments | 100.0% |
| Fact recall | 93.8% |
| Hallucinated numbers | 0.0% |
| Answers with fabricated citations | 0.0% |
| Abstains when data is unavailable | 100.0% |
| Refuses writes/advice | 100.0% |
| Injection resistance | 100.0% |
| Credential rejection | 100.0% |
| Secret leaks | 0 |
| Provider/run errors | 0.0% |
| Latency p50 (ms) | 2,386 |
| Latency p95 (ms) | 5,639 |
| Model calls / query | 2.1 |
| Input tokens / query | 4,522 |
| Output tokens / query | 430 |
| Cost / 1k queries (USD) | – |

## Pass rate by category

| Category | groq-gpt-oss-120b |
|---|---:|
| abstain | 100.0% |
| credential | 100.0% |
| fact | 100.0% |
| injection | 100.0% |
| multi_step | 33.3% |
| refuse | 100.0% |
| skill | 100.0% |

Metric definitions and limits: [docs/evaluation.md](../../../docs/evaluation.md).
