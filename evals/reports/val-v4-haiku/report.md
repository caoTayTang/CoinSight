# CoinSight agent eval — split `val`

28 cases per route · backend `live` · generated 2026-10-23T07:01:46.895521+00:00

| Metric | bedrock-haiku<br>`global.anthropic.claude-haiku-4-5-20251001-v1:0` |
|---|---:|
| Pass rate | 92.9% |
| Pass rate (excl. provider errors) | 96.3% |
| Tool selection | 95.8% |
| Arguments | 88.9% |
| Fact recall | 100.0% |
| Hallucinated numbers | 0.0% |
| Answers with fabricated citations | 3.9% |
| Abstains when data is unavailable | 100.0% |
| Refuses writes/advice | 100.0% |
| Injection resistance | 100.0% |
| Credential rejection | 100.0% |
| Secret leaks | 0 |
| Provider/run errors | 3.6% |
| Latency p50 (ms) | 4,654 |
| Latency p95 (ms) | 9,317 |
| Model calls / query | 1.75 |
| Input tokens / query | 5,690 |
| Output tokens / query | 300 |
| Cost / 1k queries (USD) | 7.1901 |

## Pass rate by category

| Category | bedrock-haiku |
|---|---:|
| abstain | 100.0% |
| credential | 100.0% |
| fact | 92.9% |
| injection | 100.0% |
| multi_step | 66.7% |
| refuse | 100.0% |
| skill | 100.0% |

Metric definitions and limits: [docs/evaluation.md](../../../docs/evaluation.md).
