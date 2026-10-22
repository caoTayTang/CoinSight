# CoinSight agent eval — split `val`

28 cases per route · backend `live` · generated 2026-10-22T02:32:37.586486+00:00

| Metric | bedrock-haiku<br>`global.anthropic.claude-haiku-4-5-20251001-v1:0` |
|---|---:|
| Pass rate | 96.4% |
| Pass rate (excl. provider errors) | 96.4% |
| Tool selection | 95.8% |
| Arguments | 100.0% |
| Fact recall | 100.0% |
| Hallucinated numbers | 0.9% |
| Answers with fabricated citations | 0.0% |
| Abstains when data is unavailable | 100.0% |
| Refuses writes/advice | 100.0% |
| Injection resistance | 100.0% |
| Credential rejection | 100.0% |
| Secret leaks | 0 |
| Provider/run errors | 0.0% |
| Latency p50 (ms) | 4,900 |
| Latency p95 (ms) | 10,785 |
| Model calls / query | 1.79 |
| Input tokens / query | 5,390 |
| Output tokens / query | 352 |
| Cost / 1k queries (USD) | 7.1503 |

## Pass rate by category

| Category | bedrock-haiku |
|---|---:|
| abstain | 100.0% |
| credential | 100.0% |
| fact | 100.0% |
| injection | 100.0% |
| multi_step | 100.0% |
| refuse | 100.0% |
| skill | 0.0% |

Metric definitions and limits: [docs/evaluation.md](../../../docs/evaluation.md).
