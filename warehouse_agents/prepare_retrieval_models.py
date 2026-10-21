"""Explicit model download, pinned resolved commit hashes, never called by a request."""

import json
from pathlib import Path
from huggingface_hub import HfApi, snapshot_download

MODELS = {
    'embedding': 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
    'reranker': 'cross-encoder/ms-marco-MiniLM-L-2-v2',
}


def main():
    root = Path('data/models/sre-retrieval')
    root.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for role, model in MODELS.items():
        commit = HfApi().model_info(model).sha
        path = root / role
        snapshot_download(
            model,
            revision=commit,
            local_dir=path,
            allow_patterns=['*.json', '*.txt', '*.safetensors', '*.model', 'modules.json', '1_Pooling/*'],
            ignore_patterns=['onnx/*', 'openvino/*', '*.bin', '*.h5'],
        )
        manifest[role] = {'model': model, 'revision': commit, 'path': str(path.resolve())}
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
