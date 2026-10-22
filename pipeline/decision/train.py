"""Train, validate, seal, test and report one immutable forecast snapshot."""
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from pipeline.decision.artifacts.store import ArtifactStore, RunPaths
from pipeline.decision.cli import load_trained_model
from pipeline.decision.config import (
    ArtifactConfig,
    TrainingConfig,
    XGBoostConfig,
    load_forecast_data_config,
    training_config_from_artifact,
)
from pipeline.decision.data.dataloader import load_model_data
from pipeline.decision.data.scaler import TargetScaler
from pipeline.decision.data.snapshot import SnapshotBuilder
from pipeline.decision.evaluation.backtest import ForecastBacktester
from pipeline.decision.evaluation.evaluator import ModelEvaluator
from pipeline.decision.evaluation.report import (
    compute_direction_head_diagnostics,
    compute_quantile_diagnostics,
    write_test_diagnostic_report,
)
from pipeline.decision.training.run_training import TrainingOrchestrator
from pipeline.decision.training.torch_trainer import TorchTrainer
from pipeline.decision.types import DatasetSplit, ModelType


SUPPORTED_MODELS = (ModelType.XGBOOST, ModelType.GRU, ModelType.LSTM)


def resolve_snapshot_symbol(
    snapshot_root: Path, snapshot_id: str, requested: str | None
) -> str:
    directory = Path(snapshot_root) / snapshot_id
    if not directory.exists():
        raise FileNotFoundError(f"snapshot does not exist: {directory}")
    available = sorted(
        child.name.upper()
        for child in directory.iterdir()
        if child.is_dir() and (child / "manifest.json").exists()
    )
    if requested is not None:
        symbol = requested.upper()
        if symbol not in available:
            raise FileNotFoundError(
                f"snapshot {snapshot_id} has no symbol {symbol}; available={available}"
            )
        return symbol
    if len(available) != 1:
        raise ValueError(
            "--symbol is required when a snapshot id contains zero or multiple symbols; "
            f"available={available}"
        )
    return available[0]


def evaluator_from_manifest(manifest: dict) -> ModelEvaluator:
    frequency = manifest.get("frequency", "1h")
    return ModelEvaluator(
        rolling_periods=int(manifest.get(
            "rolling_baseline_periods",
            manifest.get("rolling_baseline_hours", 24),
        )),
        minimum_month_samples=int(manifest.get(
            "minimum_month_samples", 20 if frequency == "1d" else 500
        )),
    )


def _manifest_extra(run: RunPaths) -> dict:
    manifest_path = run.directory / "manifest.json"
    if not manifest_path.exists():
        return {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        key: value
        for key, value in manifest.items()
        if key not in {"status", "files", "finished_at"}
    }


def run_final_test(
    run: RunPaths,
    snapshot,
    store: ArtifactStore,
) -> tuple[dict, dict]:
    """Consume the test split once and create metrics plus visual diagnostics."""
    store.seal_validation(run)
    store.claim_test(run)
    metadata = json.loads(
        (run.directory / "run.json").read_text(encoding="utf-8")
    )
    training_config = training_config_from_artifact(json.loads(
        (run.directory / "training_config.json").read_text(encoding="utf-8")
    ))
    target_scaler_path = run.directory / "target_scaler.json"
    target_scaler = (
        TargetScaler.load(target_scaler_path)
        if target_scaler_path.exists() else None
    )
    data = load_model_data(
        snapshot,
        run.model_type,
        batch_size=training_config.batch_size,
        seed=int(metadata["seed"]),
        num_workers=training_config.num_workers,
        pin_memory=(
            training_config.pin_memory
            and training_config.device.startswith("cuda")
        ),
        scale_targets=(
            run.model_type is ModelType.XGBOOST or target_scaler is not None
        ),
        target_scaler=target_scaler,
    )
    model = load_trained_model(run)
    predict_fn = None
    torch_trainer = None
    if run.model_type is not ModelType.XGBOOST:
        torch_trainer = TorchTrainer(training_config)
        predict_fn = torch_trainer.predict
    evaluation = ForecastBacktester(
        evaluator_from_manifest(snapshot.manifest)
    ).run_fixed_model(
        run.run_id,
        model,
        data,
        predict_fn=predict_fn,
        sealed=True,
    ).evaluation
    direction_head_diagnostics = None
    quantile_diagnostics = None
    if torch_trainer is not None and getattr(model, "quantile_output", False):
        quantiles = torch_trainer.predict_quantiles(
            model, data, DatasetSplit.TEST
        )
        if len(quantiles) != len(evaluation.predictions):
            raise ValueError("quantile predictions do not align with test rows")
        evaluation.predictions[[
            "return_q10", "return_q50", "return_q90"
        ]] = quantiles
        quantile_diagnostics = compute_quantile_diagnostics(
            evaluation.predictions
        )
    if (
        torch_trainer is not None
        and getattr(model, "separate_direction_head", False)
    ):
        probabilities = torch_trainer.predict_direction_probabilities(
            model, data, DatasetSplit.TEST
        )
        if len(probabilities) != len(evaluation.predictions):
            raise ValueError("direction-head predictions do not align with test rows")
        evaluation.predictions["direction_probability_up"] = probabilities
        direction_head_diagnostics = compute_direction_head_diagnostics(
            evaluation.predictions
        )
    metrics = {
        "model": evaluation.model.to_dict(),
        "zero_return": evaluation.zero_return.to_dict(),
        "rolling_mean": evaluation.rolling_mean.to_dict(),
        "persistence": (
            None
            if evaluation.persistence is None
            else evaluation.persistence.to_dict()
        ),
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
    store.save_json(run, "test_metrics.json", metrics)
    evaluation.monthly.to_csv(run.directory / "test_monthly.csv", index=False)
    evaluation.predictions.to_parquet(
        run.directory / "test_predictions.parquet", index=False
    )
    diagnostics = write_test_diagnostic_report(
        evaluation,
        run.directory,
        run_id=run.run_id,
        symbol=run.symbol,
        model_type=run.model_type.value,
    )
    return metrics, diagnostics.to_dict()


def execute(
    snapshot_id: str,
    *,
    symbol: str | None = None,
    model_type: ModelType | str = ModelType.GRU,
    seed: int = 42,
    device: str | None = None,
) -> dict:
    config = load_forecast_data_config()
    artifacts = ArtifactConfig()
    resolved_model = ModelType.parse(model_type)
    if resolved_model not in SUPPORTED_MODELS:
        raise ValueError("automatic training currently supports xgboost, gru and lstm")
    resolved_symbol = resolve_snapshot_symbol(
        artifacts.snapshot_root, snapshot_id, symbol
    )
    snapshot = SnapshotBuilder(
        None, config, artifacts.snapshot_root
    ).load(snapshot_id, resolved_symbol)
    base_training = TrainingConfig()
    training_config = replace(
        base_training,
        seed=seed,
        device=device or base_training.device,
    )
    orchestrator = TrainingOrchestrator(
        ArtifactStore(artifacts.run_root),
        evaluator=evaluator_from_manifest(snapshot.manifest),
        xgboost_config=replace(XGBoostConfig(), random_state=seed),
        training_config=training_config,
    )
    store = orchestrator.store
    run, training_manifest = orchestrator.run(
        resolved_symbol, resolved_model, snapshot, seed
    )
    validation_decision = training_manifest.get("validation_decision", {})
    if validation_decision.get("status") != "accepted":
        print(
            "[warning] validation rejected this candidate, but automatic mode "
            "will seal and consume the test split as explicitly requested.",
            flush=True,
        )
    print(
        "[test] sealing validation artifacts and consuming the final test split...",
        flush=True,
    )
    try:
        test_metrics, direction = run_final_test(run, snapshot, store)
        extra = _manifest_extra(run)
        extra.update({
            "automatic_test": True,
            "test_report_artifact": "test_evaluation_report.md",
            "test_confusion_matrix_artifact": "test_confusion_matrix.png",
            "test_price_plot_artifact": "test_price_forecast.png",
            "test_direction_metrics": direction,
        })
        final_manifest = store.finalize(run, "tested", extra)
        store.verify(run)
    except Exception as error:
        extra = _manifest_extra(run)
        extra.update({"automatic_test": True, "test_error": str(error)})
        store.finalize(run, "test_failed", extra)
        raise

    result = {
        "run_id": run.run_id,
        "symbol": run.symbol,
        "model_type": run.model_type.value,
        "snapshot_id": snapshot.snapshot_id,
        "validation_decision": validation_decision,
        "test_metrics": test_metrics,
        "direction_diagnostics": direction,
        "report": str(run.directory / "test_evaluation_report.md"),
        "confusion_matrix_plot": str(run.directory / "test_confusion_matrix.png"),
        "price_plot": str(run.directory / "test_price_forecast.png"),
        "manifest": final_manifest,
    }
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot_id", help="immutable snapshot id to train")
    parser.add_argument(
        "--symbol",
        help="optional when the snapshot id contains exactly one symbol",
    )
    parser.add_argument(
        "--model",
        default=ModelType.GRU.value,
        choices=[item.value for item in SUPPORTED_MODELS],
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--device",
        choices=("cpu", "cuda"),
        help="override TrainingConfig.device for GRU/LSTM",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = execute(
        args.snapshot_id,
        symbol=args.symbol,
        model_type=args.model,
        seed=args.seed,
        device=args.device,
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
