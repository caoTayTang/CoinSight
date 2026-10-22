# CoinSight agent eval — split `test`

12 cases per route · backend `live` · generated 2026-10-21T17:35:13.322305+00:00

| Metric | bedrock-haiku<br>`global.anthropic.claude-haiku-4-5-20251001-v1:0` |
|---|---:|
| Pass rate | 83.3% |
| Pass rate (excl. provider errors) | 83.3% |
| Tool selection | 100.0% |
| Arguments | 100.0% |
| Fact recall | 100.0% |
| Hallucinated numbers | 1.2% |
| Answers with fabricated citations | 8.3% |
| Abstains when data is unavailable | 100.0% |
| Refuses writes/advice | 50.0% |
| Injection resistance | 0.0% |
| Credential rejection | – |
| Secret leaks | 0 |
| Provider/run errors | 0.0% |
| Latency p50 (ms) | 6,516 |
| Latency p95 (ms) | 9,772 |
| Model calls / query | 1.83 |
| Input tokens / query | 5,297 |
| Output tokens / query | 353 |
| Cost / 1k queries (USD) | 7.0621 |

## Pass rate by category

| Category | bedrock-haiku |
|---|---:|
| abstain | 100.0% |
| fact | 100.0% |
| injection | 0.0% |
| multi_step | 100.0% |
| refuse | 50.0% |
| skill | 100.0% |

Metric definitions and limits: [docs/evaluation.md](../../../docs/evaluation.md).
