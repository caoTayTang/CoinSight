# CoinSight agent eval — split `train`

29 cases per route · backend `live` · generated 2026-10-23T08:35:41.180435+00:00

| Metric | bedrock-haiku<br>`global.anthropic.claude-haiku-4-5-20251001-v1:0` |
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
| Latency p50 (ms) | 4,260 |
| Latency p95 (ms) | 6,847 |
| Model calls / query | 1.83 |
| Input tokens / query | 6,325 |
| Output tokens / query | 207 |
| Cost / 1k queries (USD) | 7.3585 |

## Pass rate by category

| Category | bedrock-haiku |
|---|---:|
| abstain | 100.0% |
| credential | 100.0% |
| fact | 93.8% |
| injection | 100.0% |
| multi_step | 100.0% |
| refuse | 100.0% |
| skill | 100.0% |

Metric definitions and limits: [docs/evaluation.md](../../../docs/evaluation.md).
