# CoinSight agent eval — split `dev-v2`

29 cases per route · backend `live` · generated rebuilt from results

| Metric | bedrock-haiku<br>`global.anthropic.claude-haiku-4-5-20251001-v1:0` | groq-gpt-oss-120b<br>`openai/gpt-oss-120b` |
|---|---:|---:|
| Pass rate | 82.8% | 96.5% |
| Pass rate (excl. provider errors) | 82.8% | 96.5% |
| Tool selection | 100.0% | 100.0% |
| Arguments | 100.0% | 100.0% |
| Fact recall | 93.8% | 96.9% |
| Hallucinated numbers | 1.3% | 0.0% |
| Answers with fabricated citations | 7.1% | 0.0% |
| Abstains when data is unavailable | 66.7% | 100.0% |
| Refuses writes/advice | 100.0% | 100.0% |
| Injection resistance | 50.0% | 100.0% |
| Credential rejection | 100.0% | 100.0% |
| Secret leaks | 0 | 0 |
| Provider/run errors | 0.0% | 0.0% |
| Latency p50 (ms) | 5,299 | 4,426 |
| Latency p95 (ms) | 8,271 | 53,874 |
| Model calls / query | 1.83 | 2.31 |
| Input tokens / query | 5,260 | 4,555 |
| Output tokens / query | 358 | 600 |
| Cost / 1k queries (USD) | 7.0507 | – |

## Pass rate by category

| Category | bedrock-haiku | groq-gpt-oss-120b |
|---|---:|---:|
| abstain | 66.7% | 100.0% |
| credential | 100.0% | 100.0% |
| fact | 87.5% | 100.0% |
| injection | 50.0% | 100.0% |
| multi_step | 66.7% | 66.7% |
| refuse | 100.0% | 100.0% |
| skill | 100.0% | 100.0% |

Metric definitions and limits: [docs/evaluation.md](../../../docs/evaluation.md).
