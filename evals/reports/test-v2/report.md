# CoinSight agent eval — split `test-v2`

28 cases per route · backend `live` · generated rebuilt from results

| Metric | bedrock-haiku<br>`global.anthropic.claude-haiku-4-5-20251001-v1:0` | groq-gpt-oss-120b<br>`openai/gpt-oss-120b` |
|---|---:|---:|
| Pass rate | 96.4% | 75.0% |
| Pass rate (excl. provider errors) | 96.4% | 77.8% |
| Tool selection | 100.0% | 91.7% |
| Arguments | 100.0% | 88.9% |
| Fact recall | 100.0% | 100.0% |
| Hallucinated numbers | 0.8% | 5.6% |
| Answers with fabricated citations | 0.0% | 0.0% |
| Abstains when data is unavailable | 100.0% | 75.0% |
| Refuses writes/advice | 100.0% | 66.7% |
| Injection resistance | 100.0% | 50.0% |
| Credential rejection | 100.0% | 100.0% |
| Secret leaks | 0 | 0 |
| Provider/run errors | 0.0% | 3.6% |
| Latency p50 (ms) | 6,567 | 3,780 |
| Latency p95 (ms) | 11,583 | 7,989 |
| Model calls / query | 1.82 | 2.07 |
| Input tokens / query | 5,363 | 4,211 |
| Output tokens / query | 365 | 592 |
| Cost / 1k queries (USD) | 7.1886 | – |

## Pass rate by category

| Category | bedrock-haiku | groq-gpt-oss-120b |
|---|---:|---:|
| abstain | 100.0% | 75.0% |
| credential | 100.0% | 100.0% |
| fact | 100.0% | 92.9% |
| injection | 100.0% | 50.0% |
| multi_step | 100.0% | 33.3% |
| refuse | 100.0% | 66.7% |
| skill | 0.0% | 0.0% |

Metric definitions and limits: [docs/evaluation.md](../../../docs/evaluation.md).
