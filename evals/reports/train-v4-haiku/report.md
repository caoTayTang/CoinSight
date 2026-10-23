# CoinSight agent eval — split `train`

29 cases per route · backend `live` · generated 2026-10-23T06:58:32.513926+00:00

| Metric | bedrock-haiku<br>`global.anthropic.claude-haiku-4-5-20251001-v1:0` |
|---|---:|
| Pass rate | 89.7% |
| Pass rate (excl. provider errors) | 89.7% |
| Tool selection | 100.0% |
| Arguments | 100.0% |
| Fact recall | 93.8% |
| Hallucinated numbers | 0.0% |
| Answers with fabricated citations | 3.6% |
| Abstains when data is unavailable | 100.0% |
| Refuses writes/advice | 100.0% |
| Injection resistance | 50.0% |
| Credential rejection | 100.0% |
| Secret leaks | 0 |
| Provider/run errors | 0.0% |
| Latency p50 (ms) | 4,849 |
| Latency p95 (ms) | 9,069 |
| Model calls / query | 1.86 |
| Input tokens / query | 6,008 |
| Output tokens / query | 311 |
| Cost / 1k queries (USD) | 7.5624 |

## Pass rate by category

| Category | bedrock-haiku |
|---|---:|
| abstain | 100.0% |
| credential | 100.0% |
| fact | 93.8% |
| injection | 50.0% |
| multi_step | 66.7% |
| refuse | 100.0% |
| skill | 100.0% |

Metric definitions and limits: [docs/evaluation.md](../../../docs/evaluation.md).
