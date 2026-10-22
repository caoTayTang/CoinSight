# CoinSight agent eval — split `dev`

29 cases per route · backend `live` · generated 2026-10-21T17:33:17.712034+00:00

| Metric | groq-gpt-oss-120b<br>`openai/gpt-oss-120b` | bedrock-haiku<br>`global.anthropic.claude-haiku-4-5-20251001-v1:0` | groq-gpt-oss-20b<br>`openai/gpt-oss-20b` |
|---|---:|---:|---:|
| Pass rate | 93.1% | 89.7% | 89.7% |
| Pass rate (excl. provider errors) | 93.1% | 89.7% | 89.7% |
| Tool selection | 100.0% | 100.0% | 100.0% |
| Arguments | 100.0% | 100.0% | 100.0% |
| Fact recall | 96.9% | 100.0% | 96.9% |
| Hallucinated numbers | 0.9% | 0.8% | 1.1% |
| Answers with fabricated citations | 0.0% | 0.0% | 0.0% |
| Abstains when data is unavailable | 100.0% | 100.0% | 100.0% |
| Refuses writes/advice | 100.0% | 33.3% | 100.0% |
| Injection resistance | 100.0% | 100.0% | 100.0% |
| Credential rejection | 100.0% | 100.0% | 100.0% |
| Secret leaks | 0 | 0 | 0 |
| Provider/run errors | 0.0% | 0.0% | 0.0% |
| Latency p50 (ms) | 3,541 | 5,860 | 2,784 |
| Latency p95 (ms) | 9,020 | 8,921 | 10,776 |
| Model calls / query | 2.17 | 1.9 | 2.24 |
| Input tokens / query | 4,429 | 5,668 | 4,443 |
| Output tokens / query | 537 | 361 | 513 |
| Cost / 1k queries (USD) | – | 7.4725 | – |

## Pass rate by category

| Category | groq-gpt-oss-120b | bedrock-haiku | groq-gpt-oss-20b |
|---|---:|---:|---:|
| abstain | 100.0% | 100.0% | 100.0% |
| credential | 100.0% | 100.0% | 100.0% |
| fact | 100.0% | 93.8% | 93.8% |
| injection | 100.0% | 100.0% | 100.0% |
| multi_step | 33.3% | 100.0% | 33.3% |
| refuse | 100.0% | 33.3% | 100.0% |
| skill | 100.0% | 100.0% | 100.0% |

Metric definitions and limits: [docs/evaluation.md](../../../docs/evaluation.md).
