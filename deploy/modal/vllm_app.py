"""Serve an open-weight model with vLLM on Modal, as an OpenAI-compatible endpoint for the eval and router.

Same image and flags as deploy/vllm/compose.yml. One model per app; pick it at deploy time:

  uvx modal secret create coinsight-vllm VLLM_API_KEY=<random>     # once; also put it in .env as SELFHOSTED_API_KEY
  COINSIGHT_MODEL=Qwen/Qwen3-8B     uvx modal deploy deploy/modal/vllm_app.py
  COINSIGHT_MODEL=Qwen/Qwen3-8B-FP8 uvx modal deploy deploy/modal/vllm_app.py
  uvx modal app stop coinsight-qwen3-8b                            # stop billing when done

The URL is public, so vLLM requires the API key. One container at most, so benchmarks measure one GPU,
and it scales to zero after a few idle minutes. The first request after that waits for a cold start.
"""

import os
import subprocess

import modal

MODEL = os.environ.get('COINSIGHT_MODEL', 'Qwen/Qwen3-8B')
GPU = os.environ.get('COINSIGHT_GPU', 'L40S')
APP = 'coinsight-' + MODEL.split('/')[-1].lower().replace('.', '-')
MINUTES = 60

image = (
    modal.Image.from_registry('vllm/vllm-openai:v0.10.0')
    .entrypoint([])
    # Modal looks for `python`; the vLLM image only has python3.
    .run_commands('ln -sf "$(command -v python3)" /usr/local/bin/python')
    .env({'COINSIGHT_MODEL': MODEL, 'COINSIGHT_GPU': GPU, 'HF_HUB_ENABLE_HF_TRANSFER': '1'})
)
hf_cache = modal.Volume.from_name('huggingface-cache', create_if_missing=True)
vllm_cache = modal.Volume.from_name('vllm-cache', create_if_missing=True)

app = modal.App(APP)


@app.function(
    image=image,
    gpu=GPU,
    secrets=[modal.Secret.from_name('coinsight-vllm')],
    volumes={'/root/.cache/huggingface': hf_cache, '/root/.cache/vllm': vllm_cache},
    max_containers=1,
    scaledown_window=5 * MINUTES,
    timeout=20 * MINUTES,
)
@modal.concurrent(max_inputs=64)
@modal.web_server(port=8000, startup_timeout=15 * MINUTES)
def serve():
    command = [
        'vllm',
        'serve',
        MODEL,
        '--host=0.0.0.0',
        '--port=8000',
        '--api-key=' + os.environ['VLLM_API_KEY'],
        '--max-model-len=16384',
        '--gpu-memory-utilization=0.90',
        # The agent relies on native tool calls; Qwen3 uses the Hermes tool-call format.
        '--enable-auto-tool-choice',
        '--tool-call-parser=hermes',
        '--reasoning-parser=qwen3',
    ]
    subprocess.Popen(command)
