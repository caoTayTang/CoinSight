"""Chronological forecast backtests; no trading/PnL assumptions."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import pandas as pd

from pipeline.decision.data.dataloader import ForecastDataModule
from pipeline.decision.evaluation.evaluator import EvaluationReport, ModelEvaluator
from pipeline.decision.types import DatasetSplit, ModelType, TimeFold


@dataclass(frozen=True)
class BacktestReport:
    run_id: str
    mode: str
    evaluation: EvaluationReport


class ForecastBacktester:
    def __init__(self, evaluator: ModelEvaluator | None = None):
        self.evaluator = evaluator or ModelEvaluator()

    def run_fixed_model(
        self,
        run_id: str,
        model,
        data: ForecastDataModule,
        predict_fn: Callable | None = None,
        *,
        sealed: bool = False,
    ) -> BacktestReport:
        if not sealed:
            raise PermissionError("final test backtest requires a sealed validation run")
        report = self.evaluator.evaluate(
            model, data, DatasetSplit.TEST, predict_fn=predict_fn
        )
        if not pd.to_datetime(report.predictions["target_time"], utc=True).is_monotonic_increasing:
            raise ValueError("backtest predictions are not chronological")
        return BacktestReport(run_id, "fixed_model", report)

    def run_walk_forward(
        self,
        model_type: ModelType,
        folds: Sequence[TimeFold],
        train_and_predict: Callable[[ModelType, TimeFold], pd.DataFrame],
    ) -> pd.DataFrame:
        predictions = []
        previous_end = None
        for fold in folds:
            if previous_end is not None and fold.validation_start < previous_end:
                raise ValueError("walk-forward validation folds overlap")
            frame = train_and_predict(model_type, fold)
            if not frame.empty:
                targets = pd.to_datetime(frame["target_time"], utc=True)
                if targets.min() < pd.Timestamp(fold.validation_start) or targets.max() >= pd.Timestamp(fold.validation_end):
                    raise ValueError("walk-forward callback returned predictions outside its fold")
            predictions.append(frame)
            previous_end = fold.validation_end
        return pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame()
