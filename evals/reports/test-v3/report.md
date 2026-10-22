# CoinSight agent eval — split `test`

12 cases per route · backend `live` · generated 2026-10-21T17:36:35.043330+00:00

| Metric | groq-gpt-oss-120b<br>`openai/gpt-oss-120b` | groq-gpt-oss-20b<br>`openai/gpt-oss-20b` | bedrock-haiku<br>`global.anthropic.claude-haiku-4-5-20251001-v1:0` |
|---|---:|---:|---:|
| Pass rate | 91.7% | 100.0% | 83.3% |
| Pass rate (excl. provider errors) | 91.7% | 100.0% | 83.3% |
| Tool selection | 100.0% | 100.0% | 100.0% |
| Arguments | 100.0% | 100.0% | 100.0% |
| Fact recall | 100.0% | 100.0% | 100.0% |
| Hallucinated numbers | 1.1% | 0.0% | 1.2% |
| Answers with fabricated citations | 0.0% | 0.0% | 8.3% |
| Abstains when data is unavailable | 100.0% | 100.0% | 100.0% |
| Refuses writes/advice | 100.0% | 100.0% | 50.0% |
| Injection resistance | 100.0% | 100.0% | 0.0% |
| Credential rejection | – | – | – |
| Secret leaks | 0 | 0 | 0 |
| Provider/run errors | 0.0% | 0.0% | 0.0% |
| Latency p50 (ms) | 3,357 | 2,923 | 6,516 |
| Latency p95 (ms) | 5,014 | 4,939 | 9,772 |
| Model calls / query | 2.17 | 2.33 | 1.83 |
| Input tokens / query | 4,132 | 4,482 | 5,297 |
| Output tokens / query | 579 | 489 | 353 |
| Cost / 1k queries (USD) | – | – | 7.0621 |

## Pass rate by category

| Category | groq-gpt-oss-120b | groq-gpt-oss-20b | bedrock-haiku |
|---|---:|---:|---:|
| abstain | 100.0% | 100.0% | 100.0% |
| fact | 100.0% | 100.0% | 100.0% |
| injection | 100.0% | 100.0% | 0.0% |
| multi_step | 100.0% | 100.0% | 100.0% |
| refuse | 100.0% | 100.0% | 50.0% |
| skill | 0.0% | 100.0% | 100.0% |

Metric definitions and limits: [docs/evaluation.md](../../../docs/evaluation.md).
