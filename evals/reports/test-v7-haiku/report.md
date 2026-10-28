# CoinSight agent eval — split `test`

14 cases per route · backend `live` · generated 2026-10-25T03:31:28.619195+00:00

| Metric | bedrock-haiku<br>`global.anthropic.claude-haiku-4-5-20251001-v1:0` |
|---|---:|
| Pass rate | 92.9% |
| Pass rate (excl. provider errors) | 92.9% |
| Tool selection | 100.0% |
| Arguments | 100.0% |
| Fact recall | 100.0% |
| Hallucinated numbers | 1.1% |
| Answers with fabricated citations | 0.0% |
| Abstains when data is unavailable | 100.0% |
| Refuses writes/advice | 50.0% |
| Injection resistance | 100.0% |
| Credential rejection | – |
| Secret leaks | 0 |
| Provider/run errors | 0.0% |
| Latency p50 (ms) | 4,198 |
| Latency p95 (ms) | 7,042 |
| Model calls / query | 1.79 |
| Input tokens / query | 6,238 |
| Output tokens / query | 218 |
| Cost / 1k queries (USD) | 7.3273 |

## Pass rate by category

| Category | bedrock-haiku |
|---|---:|
| abstain | 100.0% |
| clarify | 100.0% |
| fact | 100.0% |
| injection | 100.0% |
| multi_step | 100.0% |
| refuse | 50.0% |
| skill | 100.0% |

Metric definitions and limits: [docs/evaluation.md](../../../docs/evaluation.md).
