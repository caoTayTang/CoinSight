"""Command-line interface for hourly or daily forecasting workflows."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from pipeline.decision.artifacts.store import ArtifactStore, RunPaths
from pipeline.decision.config import (
    ArtifactConfig,
    RecurrentConfig,
    TrainingConfig,
    XGBoostConfig,
    last_closed_hour,
    last_closed_period,
    load_forecast_data_config,
    recurrent_config_from_artifact,
    training_config_from_artifact,
)
from pipeline.decision.data.backfill import BackfillService
from pipeline.decision.data.dataloader import load_model_data
from pipeline.decision.data.scaler import TargetScaler
from pipeline.decision.data.snapshot import SnapshotBuilder
from pipeline.decision.data.warehouse_repository import (
    HourlyCandleRepository,
    candle_repository,
)
from pipeline.decision.evaluation.backtest import ForecastBacktester
from pipeline.decision.evaluation.evaluator import ModelEvaluator
from pipeline.decision.evaluation.report import (
    compute_direction_head_diagnostics,
    compute_quantile_diagnostics,
)
from pipeline.decision.models.factory import build_model
from pipeline.decision.models.xgboost_regressor import XGBoostForecastModel
from pipeline.decision.training.run_training import TrainingOrchestrator
from pipeline.decision.training.torch_trainer import TorchTrainer
from pipeline.decision.types import DatasetSplit, ModelType, utc_datetime


def parse_symbols(value: str) -> list[str]:
    return [item.strip().upper() for item in value.split(",") if item.strip()]


def print_json(value) -> None:
    print(json.dumps(value, indent=2, default=str))


def find_run(root: Path, run_id: str) -> RunPaths:
    matches = list(root.glob(f"*/*/{run_id}"))
    if len(matches) != 1:
        raise FileNotFoundError(f"expected one run directory for {run_id}, found {len(matches)}")
    directory = matches[0]
    return RunPaths(run_id, directory.parents[1].name, ModelType.parse(directory.parent.name), directory)


def load_trained_model(run: RunPaths):
    config = json.loads((run.directory / "model_config.json").read_text(encoding="utf-8"))
    if run.model_type is ModelType.XGBOOST:
        features = json.loads((run.directory / "feature_names.json").read_text(encoding="utf-8"))
        return XGBoostForecastModel.load(
            run.directory / "model.ubj", XGBoostConfig(**config), tuple(features["feature_names"])
        )
    try:
        import torch
    except ImportError as error:
        raise RuntimeError("PyTorch is required to load GRU/LSTM checkpoints") from error
    model = build_model(run.model_type, recurrent_config_from_artifact(config))
    checkpoint = torch.load(run.directory / "model.pt", map_location="cpu", weights_only=True)
    model.load_state_dict(checkpoint["state_dict"])
    return model


def main() -> None:
    config = load_forecast_data_config()
    artifacts = ArtifactConfig()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    audit = commands.add_parser("audit-data")
    audit.add_argument("--symbols", default=",".join(config.symbols))
    audit.add_argument("--end", default=None)

    backfill = commands.add_parser("backfill")
    backfill.add_argument("--symbols", required=True)
    backfill.add_argument("--start", required=True, help="YYYY-MM")
    backfill.add_argument("--end", default=None, help="exclusive UTC cutoff")
    backfill.add_argument("--workers", type=int)

    dataset = commands.add_parser("build-dataset")
    dataset.add_argument("--symbol", required=True)
    dataset.add_argument("--cutoff", default=None)

    train = commands.add_parser("train")
    train.add_argument("--symbol", required=True)
    train.add_argument("--model", required=True, choices=[item.value for item in ModelType])
    train.add_argument("--snapshot-id", required=True)
    train.add_argument("--seed", type=int, default=42)

    resume = commands.add_parser("resume")
    resume.add_argument("--run-id", required=True)

    seal = commands.add_parser("seal")
    seal.add_argument("--run-id", required=True)

    backtest = commands.add_parser("backtest")
    backtest.add_argument("--run-id", required=True)

    args = parser.parse_args()
    repository = candle_repository(
        config.frequency, source_code=config.source_code
    )

    if args.command == "audit-data":
        symbols = parse_symbols(args.symbols)
        # Archive backfill remains hourly because it is responsible for the raw
        # 1h source. Dataset building below reads the configured 1h/1d fact.
        hourly_repository = HourlyCandleRepository(source_code=config.source_code)
        end = utc_datetime(args.end) if args.end else last_closed_hour()
        reports = BackfillService(hourly_repository).audit(
            symbols, config.history_start, end
        )
        print_json([report.to_dict() for report in reports])
        return
    if args.command == "backfill":
        hourly_repository = HourlyCandleRepository(source_code=config.source_code)
        result = BackfillService(hourly_repository).backfill(
            parse_symbols(args.symbols), args.start, args.workers,
            end=utc_datetime(args.end) if args.end else None,
        )
        print_json(asdict(result))
        return
    if args.command == "build-dataset":
        symbol = args.symbol.upper()
        cutoff = (
            utc_datetime(args.cutoff)
            if args.cutoff else last_closed_period(config.frequency)
        )
        snapshot = SnapshotBuilder(repository, config, artifacts.snapshot_root).build(
            symbol, config.history_start[symbol], cutoff
        )
        print_json(snapshot.manifest)
        return
    store = ArtifactStore(artifacts.run_root)
    if args.command == "train":
        symbol = args.symbol.upper()
        snapshot = SnapshotBuilder(repository, config, artifacts.snapshot_root).load(
            args.snapshot_id, symbol
        )
        run, manifest = TrainingOrchestrator(store).run(
            symbol, ModelType.parse(args.model), snapshot, args.seed
        )
        print_json(manifest)
        return
    if args.command == "resume":
        run = find_run(artifacts.run_root, args.run_id)
        metadata = json.loads((run.directory / "run.json").read_text(encoding="utf-8"))
        if run.model_type not in {ModelType.GRU, ModelType.LSTM}:
            raise ValueError("checkpoint resume is currently supported for GRU/LSTM only")
        model_config = recurrent_config_from_artifact(json.loads(
            (run.directory / "model_config.json").read_text(encoding="utf-8")
        ))
        training_config = training_config_from_artifact(json.loads(
            (run.directory / "training_config.json").read_text(encoding="utf-8")
        ))
        snapshot = SnapshotBuilder(repository, config, artifacts.snapshot_root).load(
            metadata["snapshot_id"], run.symbol
        )
        _, manifest = TrainingOrchestrator(
            store,
            recurrent_config=model_config,
            training_config=training_config,
        ).run(
            run.symbol,
            run.model_type,
            snapshot,
            int(metadata["seed"]),
            resume_run=run,
        )
        print_json(manifest)
        return
    run = find_run(artifacts.run_root, args.run_id)
    if args.command == "seal":
        store.seal_validation(run)
        print_json({"run_id": run.run_id, "status": "sealed_for_test"})
        return
    if args.command == "backtest":
        store.claim_test(run)
        run_metadata = json.loads((run.directory / "run.json").read_text(encoding="utf-8"))
        snapshot = SnapshotBuilder(repository, config, artifacts.snapshot_root).load(
            run_metadata["snapshot_id"], run.symbol
        )
        target_scaler_path = run.directory / "target_scaler.json"
        target_scaler = (
            TargetScaler.load(target_scaler_path)
            if target_scaler_path.exists() else None
        )
        stored_training_config = training_config_from_artifact(json.loads(
            (run.directory / "training_config.json").read_text(encoding="utf-8")
        ))
        data = load_model_data(
            snapshot,
            run.model_type,
            batch_size=stored_training_config.batch_size,
            seed=int(run_metadata["seed"]),
            num_workers=stored_training_config.num_workers,
            pin_memory=(
                stored_training_config.pin_memory
                and stored_training_config.device.startswith("cuda")
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
            torch_trainer = TorchTrainer(stored_training_config)
            predict_fn = torch_trainer.predict
        evaluator = ModelEvaluator(
            rolling_periods=int(snapshot.manifest.get(
                "rolling_baseline_periods",
                snapshot.manifest.get("rolling_baseline_hours", 24),
            )),
            minimum_month_samples=int(snapshot.manifest.get(
                "minimum_month_samples",
                20 if snapshot.manifest.get("frequency") == "1d" else 500,
            )),
        )
        report = ForecastBacktester(evaluator).run_fixed_model(
            run.run_id, model, data, predict_fn=predict_fn, sealed=True
        )
        direction_head_diagnostics = None
        quantile_diagnostics = None
        if torch_trainer is not None and getattr(model, "quantile_output", False):
            quantiles = torch_trainer.predict_quantiles(
                model, data, DatasetSplit.TEST
            )
            report.evaluation.predictions[[
                "return_q10", "return_q50", "return_q90"
            ]] = quantiles
            quantile_diagnostics = compute_quantile_diagnostics(
                report.evaluation.predictions
            )
        if (
            torch_trainer is not None
            and getattr(model, "separate_direction_head", False)
        ):
            probabilities = torch_trainer.predict_direction_probabilities(
                model, data, DatasetSplit.TEST
            )
            report.evaluation.predictions["direction_probability_up"] = probabilities
            direction_head_diagnostics = compute_direction_head_diagnostics(
                report.evaluation.predictions
            )
        payload = {
            "model": report.evaluation.model.to_dict(),
            "zero_return": report.evaluation.zero_return.to_dict(),
            "rolling_mean": report.evaluation.rolling_mean.to_dict(),
            "persistence": (
                None
                if report.evaluation.persistence is None
                else report.evaluation.persistence.to_dict()
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
        store.save_json(run, "test_metrics.json", payload)
        report.evaluation.monthly.to_csv(run.directory / "test_monthly.csv", index=False)
        report.evaluation.predictions.to_parquet(
            run.directory / "test_predictions.parquet", index=False
        )
        manifest = json.loads((run.directory / "manifest.json").read_text(encoding="utf-8"))
        store.finalize(run, "tested", {
            key: value for key, value in manifest.items()
            if key not in {"status", "files", "finished_at"}
        })
        print_json(payload)


if __name__ == "__main__":
    main()
