# Self-hosted serving and benchmark

The agent's router speaks to any OpenAI-compatible server through the `openai_compatible` provider, so a
self-hosted open-weight model is just another route. The same eval suite then measures quality, and
`evals/serving_bench.py` measures speed and cost on the agent's real request shape.

## 1. Serve a model (GPU host)

```bash
# On a host with one NVIDIA GPU (24 GB+ for BF16 8B; FP8 needs Ada/Hopper: L4, L40S, H100)
docker compose -f deploy/vllm/compose.yml up -d qwen3-8b        # BF16, port 8100
docker compose -f deploy/vllm/compose.yml up -d qwen3-8b-fp8    # FP8 weights, port 8101 (one at a time)

# From your laptop
ssh -N -L 8100:127.0.0.1:8100 -L 8101:127.0.0.1:8101 gpu-host
curl http://127.0.0.1:8100/v1/models
```

The server must enable tool calling (`--enable-auto-tool-choice --tool-call-parser hermes`); the agent
depends on native tool calls, not on parsing tool calls out of text.

## 2. Quality: same eval as the hosted models

```bash
make eval-db                                   # disposable Postgres on 127.0.0.1:15440
make eval ROUTES=selfhosted-qwen3-8b,selfhosted-qwen3-8b-fp8,groq-gpt-oss-120b SPLIT=test
```

Routes are defined in `evals/routes.json`. The self-hosted routes need no API key.

## 3. Speed and cost

```bash
python -m evals.serving_bench --base-url http://127.0.0.1:8100/v1 --model Qwen/Qwen3-8B \
  --concurrency 1,8,32 --requests 64 --gpu "1x L40S" --gpu-usd-per-hour <price> \
  --out evals/reports/serving/qwen3-8b-bf16.json
```

The report includes time to first token (p50/p95), end-to-end latency, output tokens/s and requests/s
at each concurrency level, plus HTTP 429s counted separately. Self-hosted cost per 1,000 queries is
`GPU $/hour ÷ (requests/s × 3600) × 1000` at the best measured throughput. Compare it with token-priced
APIs using `evals/pricing.json`.

## What to look for

- **Quality gap:** pass rate, tool selection and hallucinated-number rate of the 8B model compared with the hosted models.
- **Quantization cost:** FP8 against BF16 on the same eval. Did tool-call accuracy drop?
- **Concurrency:** vLLM's continuous batching should raise tokens/s with concurrency while p95 TTFT grows.
  The useful operating point is the highest concurrency whose p95 latency still fits the agent's budget.

## Status

The code paths are built: the router provider, the vLLM compose file, the benchmark, and eval routes.
The GPU runs have **not been done yet** because they need a GPU host. Record the results here with the
vLLM version, GPU type and date.
