"""End-to-end offline training and validation for one symbol/model/seed."""
from __future__ import annotations

import importlib.metadata
import json
import platform
from dataclasses import asdict, replace

from pipeline.decision.artifacts.store import ArtifactStore, RunPaths
from pipeline.decision.config import (
    RecurrentConfig,
    TrainingConfig,
    XGBoostConfig,
    recurrent_config_from_artifact,
    training_config_from_artifact,
)
from pipeline.decision.data.dataloader import load_model_data
from pipeline.decision.data.scaler import TargetScaler
from pipeline.decision.evaluation.evaluator import ModelEvaluator
from pipeline.decision.evaluation.report import (
    compute_direction_head_diagnostics,
    compute_quantile_diagnostics,
)
from pipeline.decision.models.factory import build_model
from pipeline.decision.training.seed import seed_everything
from pipeline.decision.training.torch_trainer import TorchTrainer
from pipeline.decision.training.xgboost_trainer import XGBoostTrainer
from pipeline.decision.types import DatasetSnapshot, DatasetSplit, ModelType


class TrainingOrchestrator:
    def __init__(
        self,
        store: ArtifactStore,
        evaluator: ModelEvaluator | None = None,
        xgboost_config: XGBoostConfig | None = None,
        recurrent_config: RecurrentConfig | None = None,
        training_config: TrainingConfig | None = None,
    ):
        self.store = store
        self.evaluator = evaluator
        self.xgboost_config = xgboost_config or XGBoostConfig()
        self.recurrent_config = recurrent_config or RecurrentConfig()
        self.training_config = training_config or TrainingConfig()

    def run(
        self,
        symbol: str,
        model_type: ModelType | str,
        snapshot: DatasetSnapshot,
        seed: int,
        *,
        resume_run: RunPaths | None = None,
    ) -> tuple[RunPaths, dict]:
        resolved = ModelType.parse(model_type)
        evaluator = self.evaluator or ModelEvaluator(
            rolling_periods=int(snapshot.manifest.get(
                "rolling_baseline_periods",
                snapshot.manifest.get("rolling_baseline_hours", 24),
            )),
            minimum_month_samples=int(snapshot.manifest.get(
                "minimum_month_samples",
                20 if snapshot.manifest.get("frequency") == "1d" else 500,
            )),
        )
        if resolved in {ModelType.PATCHTST, ModelType.ITRANSFORMER}:
            raise NotImplementedError("Transformer model training belongs to phase 2")
        if resume_run is not None and resolved is ModelType.XGBOOST:
            raise ValueError("checkpoint resume is currently supported for GRU/LSTM only")
        seed_everything(seed)
        run = resume_run or self.store.create_run(
            symbol, resolved, snapshot.snapshot_id, seed
        )
        if run.symbol != symbol.upper() or run.model_type is not resolved:
            raise ValueError("resume run identity does not match symbol/model")
        resume_metadata = None
        if resume_run is not None:
            resume_metadata = json.loads(
                (run.directory / "run.json").read_text(encoding="utf-8")
            )
            if resume_metadata.get("snapshot_id") != snapshot.snapshot_id:
                raise ValueError("resume run snapshot does not match the requested snapshot")
            if int(resume_metadata.get("seed")) != seed:
                raise ValueError("resume run seed does not match the requested seed")
        print(
            f"[run] id={run.run_id} | symbol={symbol.upper()} | "
            f"model={resolved.value} | snapshot={snapshot.snapshot_id} | seed={seed} | "
            f"resume={'yes' if resume_run is not None else 'no'}",
            flush=True,
        )
        print("[data] loading snapshot and preparing model inputs...", flush=True)
        resume_target_scaler = None
        if resume_run is not None:
            target_scaler_path = run.directory / "target_scaler.json"
            if not target_scaler_path.exists():
                raise FileNotFoundError(
                    "run predates target standardization and cannot be resumed safely"
                )
            resume_target_scaler = TargetScaler.load(target_scaler_path)
        data = load_model_data(
            snapshot,
            resolved,
            self.training_config.batch_size,
            seed,
            num_workers=self.training_config.num_workers,
            pin_memory=(
                self.training_config.pin_memory
                and self.training_config.device.startswith("cuda")
            ),
            target_scaler=resume_target_scaler,
        )
        try:
            if resolved is ModelType.XGBOOST:
                model_config = self.xgboost_config
                model = build_model(resolved, model_config)
                trainer = XGBoostTrainer()
                effective_training = self.training_config
            else:
                model_config = replace(
                    self.recurrent_config, input_size=data.input_shape()[-1]
                )
                model = build_model(resolved, model_config)
                effective_training = TrainingConfig(**{
                    **asdict(self.training_config), "seed": seed,
                })
                trainer = TorchTrainer(effective_training)
            expected_model_config = asdict(model_config)
            expected_training_config = asdict(
                self.training_config if resolved is ModelType.XGBOOST else effective_training
            )
            if resume_run is None:
                self.store.save_json(run, "model_config.json", expected_model_config)
                self.store.save_json(run, "training_config.json", expected_training_config)
                scaler_path = self.store.save_scaler(run, data.scaler)
                target_scaler_path = self.store.save_target_scaler(
                    run, data.target_scaler
                )
            else:
                stored_model_config = json.loads(
                    (run.directory / "model_config.json").read_text(encoding="utf-8")
                )
                stored_training_config = json.loads(
                    (run.directory / "training_config.json").read_text(encoding="utf-8")
                )
                normalized_stored_model = (
                    stored_model_config
                    if resolved is ModelType.XGBOOST
                    else asdict(recurrent_config_from_artifact(stored_model_config))
                )
                if normalized_stored_model != expected_model_config:
                    raise ValueError("resume model config differs from the original run")
                normalized_stored_training = asdict(
                    training_config_from_artifact(stored_training_config)
                )
                if normalized_stored_training != expected_training_config:
                    raise ValueError("resume training config differs from the original run")
                scaler_path = run.directory / "scaler.json"
                target_scaler_path = run.directory / "target_scaler.json"
                self.store.prepare_resume(run)
            if resolved is ModelType.XGBOOST:
                train_samples = len(data.tabular(DatasetSplit.TRAIN).y)
                validation_samples = len(data.tabular(DatasetSplit.VALIDATION).y)
            else:
                train_samples = len(data.dataset(DatasetSplit.TRAIN))
                validation_samples = len(data.dataset(DatasetSplit.VALIDATION))
            print("[training-config]", flush=True)
            print(json.dumps({
                "model": asdict(model_config),
                "training": asdict(effective_training),
                "data": {
                    "train_samples": train_samples,
                    "validation_samples": validation_samples,
                    "input_shape": data.input_shape(),
                },
            }, indent=2, default=str), flush=True)
            print("[training] started", flush=True)
            if resolved is ModelType.XGBOOST:
                result = trainer.fit(model, data)
            else:
                result = trainer.fit(
                    model,
                    data,
                    checkpoint_dir=run.directory,
                    resume=resume_run is not None,
                )
            print(
                f"[training] finished | best_epoch="
                f"{None if result.best_epoch is None else result.best_epoch + 1} | "
                f"best_validation_mae={result.best_validation_mae:.8f} | "
                f"seconds={result.duration_seconds:.1f}",
                flush=True,
            )
            print(
                "[evaluation] comparing validation predictions with "
                "zero-return and rolling-mean baselines...",
                flush=True,
            )
            validation = evaluator.evaluate(
                model, data, DatasetSplit.VALIDATION, predict_fn=trainer.predict
            )
            direction_head_diagnostics = None
            quantile_diagnostics = None
            if (
                resolved is not ModelType.XGBOOST
                and getattr(model, "quantile_output", False)
            ):
                quantiles = trainer.predict_quantiles(
                    model, data, DatasetSplit.VALIDATION
                )
                if len(quantiles) != len(validation.predictions):
                    raise ValueError(
                        "quantile predictions do not align with validation rows"
                    )
                validation.predictions[[
                    "return_q10", "return_q50", "return_q90"
                ]] = quantiles
                quantile_diagnostics = compute_quantile_diagnostics(
                    validation.predictions
                )
            if (
                resolved is not ModelType.XGBOOST
                and getattr(model, "has_direction_head", False)
            ):
                direction_probabilities = trainer.predict_direction_probabilities(
                    model, data, DatasetSplit.VALIDATION
                )
                if len(direction_probabilities) != len(validation.predictions):
                    raise ValueError(
                        "direction-head predictions do not align with validation rows"
                    )
                validation.predictions["direction_probability_up"] = (
                    direction_probabilities
                )
                direction_head_diagnostics = compute_direction_head_diagnostics(
                    validation.predictions
                )
            decision = evaluator.decide_candidate(validation)
            print(json.dumps({
                "model_mae": validation.model.mae_return,
                "zero_return_mae": validation.zero_return.mae_return,
                "rolling_mean_mae": validation.rolling_mean.mae_return,
                "directional_accuracy": validation.model.directional_accuracy,
                "direction_head_accuracy": (
                    None
                    if direction_head_diagnostics is None
                    else direction_head_diagnostics.accuracy
                ),
                "quantile_diagnostics": (
                    None
                    if quantile_diagnostics is None
                    else quantile_diagnostics.to_dict()
                ),
                "persistence_diagnostics": (
                    None
                    if validation.persistence is None
                    else validation.persistence.to_dict()
                ),
                "decision": asdict(decision),
            }, indent=2, default=str), flush=True)
            model_path = self.store.save_model(run, model, model_config)
            scaler_path = self.store.save_scaler(run, data.scaler)
            target_scaler_path = self.store.save_target_scaler(
                run, data.target_scaler
            )
            self.store.save_json(run, "model_config.json", expected_model_config)
            self.store.save_json(run, "training_config.json", expected_training_config)
            self.store.save_json(run, "environment.json", {
                "python": platform.python_version(),
                "packages": {
                    name: importlib.metadata.version(name)
                    for name in ("numpy", "pandas", "pyarrow", "xgboost", "torch")
                    if self._package_exists(name)
                },
            })
            self.store.save_json(run, "training_history.json", {
                "best_epoch": result.best_epoch,
                "best_validation_mae": result.best_validation_mae,
                "duration_seconds": result.duration_seconds,
                "epochs": list(result.history),
            })
            self.store.save_json(run, "feature_names.json", {
                "feature_names": list(
                    data.tabular(DatasetSplit.TRAIN).feature_names
                    if resolved is ModelType.XGBOOST else data.scaler.feature_names
                )
            })
            validation_payload = {
                "model": validation.model.to_dict(),
                "zero_return": validation.zero_return.to_dict(),
                "rolling_mean": validation.rolling_mean.to_dict(),
                "persistence": (
                    None
                    if validation.persistence is None
                    else validation.persistence.to_dict()
                ),
                "decision": asdict(decision),
                "direction_head": (
                    None
                    if direction_head_diagnostics is None
                    else direction_head_diagnostics.to_dict()
                ),
                "quantile": (
                    None
                    if quantile_diagnostics is None
                    else quantile_diagnostics.to_dict()
                ),
            }
            self.store.save_json(run, "validation_metrics.json", validation_payload)
            validation.monthly.to_csv(run.directory / "validation_monthly.csv", index=False)
            validation.predictions.to_parquet(
                run.directory / "validation_predictions.parquet", index=False
            )
            manifest = self.store.finalize(run, decision.status, {
                "snapshot_id": snapshot.snapshot_id,
                "feature_version": snapshot.manifest["feature_version"],
                "frequency": snapshot.manifest.get("frequency", "1h"),
                "lookback_periods": snapshot.manifest.get(
                    "lookback_periods", snapshot.manifest.get("lookback_hours")
                ),
                "horizon_periods": snapshot.manifest.get(
                    "horizon_periods", snapshot.manifest.get("horizon_hours")
                ),
                "seed": seed,
                "model_artifact": model_path.name,
                "best_checkpoint_artifact": (
                    "best_checkpoint.pt" if resolved is not ModelType.XGBOOST else None
                ),
                "resume_checkpoint_artifact": (
                    "last_checkpoint.pt" if resolved is not ModelType.XGBOOST else None
                ),
                "scaler_artifact": None if scaler_path is None else scaler_path.name,
                "target_scaler_artifact": (
                    None if target_scaler_path is None else target_scaler_path.name
                ),
                "validation_decision": asdict(decision),
            })
            print(
                f"[artifacts] status={decision.status} | directory={run.directory}",
                flush=True,
            )
            return run, manifest
        except Exception as error:
            self.store.finalize(run, "failed", {
                "snapshot_id": snapshot.snapshot_id,
                "feature_version": snapshot.manifest.get("feature_version"),
                "frequency": snapshot.manifest.get("frequency", "1h"),
                "seed": seed,
                "error": str(error),
            })
            raise

    @staticmethod
    def _package_exists(name: str) -> bool:
        try:
            importlib.metadata.version(name)
            return True
        except importlib.metadata.PackageNotFoundError:
            return False
