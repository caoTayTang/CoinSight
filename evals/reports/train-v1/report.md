# CoinSight agent eval — split `train`

29 cases per route · backend `live` · generated 2026-10-21T06:59:28.005323+00:00

| Metric | groq-gpt-oss-120b<br>`openai/gpt-oss-120b` |
|---|---:|
| Pass rate | 96.5% |
| Pass rate (excl. provider errors) | 96.5% |
| Tool selection | 100.0% |
| Arguments | 100.0% |
| Fact recall | 96.9% |
| Hallucinated numbers | 0.0% |
| Answers with fabricated citations | 0.0% |
| Abstains when data is unavailable | 100.0% |
| Refuses writes/advice | 100.0% |
| Injection resistance | 100.0% |
| Credential rejection | 100.0% |
| Secret leaks | 0 |
| Provider/run errors | 0.0% |
| Latency p50 (ms) | 2,807 |
| Latency p95 (ms) | 5,168 |
| Model calls / query | 2.14 |
| Input tokens / query | 3,066 |
| Output tokens / query | 569 |
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
| runbook | 100.0% |

Metric definitions and limits: [docs/evaluation.md](../../../docs/evaluation.md).
