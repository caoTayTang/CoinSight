"""Immutable local artifacts for reproducible forecast runs."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pipeline.decision.data.scaler import SequenceScaler, TargetScaler
from pipeline.decision.types import ModelType


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class RunPaths:
    run_id: str
    symbol: str
    model_type: ModelType
    directory: Path


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def create_run(
        self, symbol: str, model_type: ModelType | str, snapshot_id: str, seed: int
    ) -> RunPaths:
        resolved = ModelType.parse(model_type)
        run_id = str(uuid4())
        directory = self.root / symbol.upper() / resolved.value / run_id
        directory.mkdir(parents=True, exist_ok=False)
        metadata = {
            "run_id": run_id,
            "symbol": symbol.upper(),
            "model_type": resolved.value,
            "snapshot_id": snapshot_id,
            "seed": seed,
            "created_at": datetime.now(UTC).isoformat(),
            "status": "running",
        }
        (directory / "run.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return RunPaths(run_id, symbol.upper(), resolved, directory)

    def prepare_resume(self, run: RunPaths) -> dict[str, Any]:
        """Reopen an interrupted recurrent run while preserving its run id."""
        run_path = run.directory / "run.json"
        if not run_path.exists():
            raise FileNotFoundError(f"run metadata does not exist: {run_path}")
        metadata = json.loads(run_path.read_text(encoding="utf-8"))
        if metadata.get("status") not in {"running", "failed"}:
            raise ValueError(
                f"run {run.run_id} has immutable status {metadata.get('status')!r}; "
                "only running or failed runs can be resumed"
            )
        if run.model_type not in {ModelType.GRU, ModelType.LSTM}:
            raise ValueError("checkpoint resume is currently supported for GRU/LSTM only")
        required = (
            "last_checkpoint.pt", "model_config.json", "training_config.json",
            "scaler.json", "target_scaler.json",
        )
        missing = [name for name in required if not (run.directory / name).exists()]
        if missing:
            raise FileNotFoundError(f"run cannot be resumed; missing artifacts: {missing}")
        metadata["status"] = "running"
        metadata["resumed_at"] = datetime.now(UTC).isoformat()
        metadata["resume_count"] = int(metadata.get("resume_count", 0)) + 1
        metadata.pop("finished_at", None)
        run_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        (run.directory / "manifest.json").unlink(missing_ok=True)
        (run.directory / "last_checkpoint.pt.tmp").unlink(missing_ok=True)
        (run.directory / "best_checkpoint.pt.tmp").unlink(missing_ok=True)
        return metadata

    def save_model(self, run: RunPaths, model, model_config: Any) -> Path:
        if run.model_type is ModelType.XGBOOST:
            path = run.directory / "model.ubj"
            model.save(path)
        else:
            try:
                import torch
            except ImportError as error:
                raise RuntimeError("PyTorch is required to save recurrent checkpoints") from error
            path = run.directory / "model.pt"
            torch.save({
                "state_dict": model.state_dict(),
                "model_type": run.model_type.value,
                "model_config": asdict(model_config),
            }, path)
        return path

    def save_scaler(self, run: RunPaths, scaler: SequenceScaler | None) -> Path | None:
        if scaler is None:
            return None
        path = run.directory / "scaler.json"
        scaler.save(path)
        return path

    def save_target_scaler(
        self, run: RunPaths, scaler: TargetScaler | None
    ) -> Path | None:
        if scaler is None:
            return None
        path = run.directory / "target_scaler.json"
        scaler.save(path)
        return path

    def save_json(self, run: RunPaths, name: str, value: Any) -> Path:
        path = run.directory / name
        path.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")
        return path

    def finalize(self, run: RunPaths, status: str, extra: dict[str, Any]) -> dict:
        run_path = run.directory / "run.json"
        run_metadata = json.loads(run_path.read_text(encoding="utf-8"))
        run_metadata["status"] = status
        run_metadata["finished_at"] = datetime.now(UTC).isoformat()
        run_path.write_text(json.dumps(run_metadata, indent=2), encoding="utf-8")
        files = {
            path.name: file_sha256(path)
            for path in sorted(run.directory.iterdir())
            if path.is_file() and path.name != "manifest.json"
        }
        manifest = {
            "run_id": run.run_id,
            "symbol": run.symbol,
            "model_type": run.model_type.value,
            "status": status,
            "finished_at": datetime.now(UTC).isoformat(),
            "files": files,
            **extra,
        }
        self.save_json(run, "manifest.json", manifest)
        return manifest

    def verify(self, run: RunPaths) -> None:
        manifest_path = run.directory / "manifest.json"
        if not manifest_path.exists():
            raise ValueError("run has not been finalized")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for name, expected in manifest["files"].items():
            path = run.directory / name
            if not path.exists() or file_sha256(path) != expected:
                raise ValueError(f"run artifact checksum mismatch: {path}")

    def seal_validation(self, run: RunPaths) -> None:
        validation = run.directory / "validation_metrics.json"
        if not validation.exists():
            raise ValueError("cannot seal a run without validation metrics")
        marker = run.directory / "SEALED_FOR_TEST"
        if marker.exists():
            raise ValueError("run is already sealed")
        marker.write_text(file_sha256(validation), encoding="utf-8")

    def claim_test(self, run: RunPaths) -> None:
        if not (run.directory / "SEALED_FOR_TEST").exists():
            raise PermissionError("run is not sealed for final test")
        marker = run.directory / "TEST_CONSUMED"
        try:
            marker.touch(exist_ok=False)
        except FileExistsError as error:
            raise PermissionError("final test has already been consumed for this run") from error
