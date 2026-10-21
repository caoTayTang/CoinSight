# SRE implementation validation — 2026-10-20

Implemented and deployed locally: allowlisted paragraph runbooks, BM25 retrieval, SRE access to model_health, exact citation ID checking, shared tool-label schemas, MCP retrieval tool. No warehouse writes or Docker control added.

- Backend: 84 passed, 3 skipped (PostgreSQL integration prerequisites).
- Frontend: 24 passed.
- Live Desk service-health + runbook and drift + runbook: HTTP 200, requested tools used, no invalid citations.
- Live final trace: `a02046456611aff1abdd6000e7ac6de3`; Jaeger API confirmed gateway/A2A, agent.task, agent.run, agent.reason, llm.provider, tool.search_runbooks and retrieval.runbooks in the same trace.
- Fixed actual A2A JSON-RPC propagation through `build_request`; regression test verifies traceparent and shared-header isolation.
- No visual browser QA performed.

## CPU retrieval benchmark

Models downloaded explicitly; resolved revisions recorded in `data/models/sre-retrieval/manifest.json`. Runtime dependencies recorded in `requirements-neural.lock`. No neural model loaded into default 768-MiB service containers.

| Mode | Recall@3 | MRR@3 | Mean warm latency ms |
|---|---:|---:|---:|
| BM25 | 1.0 | 1.0 | 0.3 |
| Dense | 1.0 | 1.0 | 6.2 |
| Hybrid RRF | 1.0 | 1.0 | 6.2 |
| Hybrid + reranker | 1.0 | 1.0 | 23.9 |

Dense first invocation included Python/library/model cold start and took about 42 seconds. Subsequent modes shared the loaded models. This is a serial local smoke benchmark, not comparable production p95 latency. Nine positive English author-created queries plus one unknown lexical query; questions were visible during development. No independent generalization, multilingual quality, answer faithfulness or production impact claim. Neural modes return ranked hits even for an unknown query; ranking scores alone cannot certify answerability. BM25 remains the serving default.

## Fine-tune status

Not trained; no CUDA GPU on this Mac ARM environment. Unsloth training, held-out generation and offline scoring scripts are present but GPU training and base/adapter generation have NOT been validated. Seed JSONL is only 4 train / 2 validation / 4 test examples: plumbing only, not a training corpus or evidence of quality. Dataset schema checks and split-leakage/scoring tests passed. No adapter promoted or served.

Read `docs/sre_rag.md` for commands, source paths and limitations. Evidence JSON lives under ignored `data/models/warehouse-agent-validation/` (`retrieval_*.json`, `sre_*_live.json`, `sre_trace_proof.json`).
