"""Deterministic seeds used by reproducible training runs."""
from __future__ import annotations

import os
import random

import numpy as np


# Required by deterministic CUDA matrix multiplications. Respect an explicit
# value supplied by the caller while keeping direct Python entrypoints safe.
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    try:
        import torch
    except ImportError:
        return
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)
