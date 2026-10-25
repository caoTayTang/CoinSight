# CoinSight agent eval — split `val`

32 cases per route · backend `live` · generated 2026-10-24T15:56:52.334829+00:00

| Metric | bedrock-haiku<br>`global.anthropic.claude-haiku-4-5-20251001-v1:0` |
|---|---:|
| Pass rate | 100.0% |
| Pass rate (excl. provider errors) | 100.0% |
| Tool selection | 96.2% |
| Arguments | 100.0% |
| Fact recall | 100.0% |
| Hallucinated numbers | 0.0% |
| Answers with fabricated citations | 0.0% |
| Abstains when data is unavailable | 100.0% |
| Refuses writes/advice | 100.0% |
| Injection resistance | 100.0% |
| Credential rejection | 100.0% |
| Secret leaks | 0 |
| Provider/run errors | 0.0% |
| Latency p50 (ms) | 4,487 |
| Latency p95 (ms) | 7,390 |
| Model calls / query | 1.75 |
| Input tokens / query | 6,370 |
| Output tokens / query | 215 |
| Cost / 1k queries (USD) | 7.4455 |

## Pass rate by category

| Category | bedrock-haiku |
|---|---:|
| abstain | 100.0% |
| clarify | 100.0% |
| credential | 100.0% |
| fact | 100.0% |
| injection | 100.0% |
| multi_step | 100.0% |
| refuse | 100.0% |
| skill | 100.0% |

Metric definitions and limits: [docs/evaluation.md](../../../docs/evaluation.md).
