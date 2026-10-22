"""Native XGBoost wrapper for next-hour log-return regression."""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.decision.config import XGBoostConfig
from pipeline.decision.types import TabularData, TrainingResult


def build_xgboost_regressor(config: XGBoostConfig):
    try:
        from xgboost import XGBRegressor
    except ImportError as error:
        raise RuntimeError("xgboost is required to build an XGBoost forecast model") from error
    return XGBRegressor(
        objective=config.objective,
        eval_metric=config.eval_metric,
        tree_method=config.tree_method,
        n_estimators=config.n_estimators,
        learning_rate=config.learning_rate,
        max_depth=config.max_depth,
        min_child_weight=config.min_child_weight,
        subsample=config.subsample,
        colsample_bytree=config.colsample_bytree,
        reg_alpha=config.reg_alpha,
        reg_lambda=config.reg_lambda,
        early_stopping_rounds=config.early_stopping_rounds,
        random_state=config.random_state,
        n_jobs=config.n_jobs,
    )


class XGBoostForecastModel:
    def __init__(self, config: XGBoostConfig | None = None, model=None):
        self.config = config or XGBoostConfig()
        self.model = model or build_xgboost_regressor(self.config)
        self.feature_names: tuple[str, ...] = ()

    @staticmethod
    def _frame(data: TabularData) -> pd.DataFrame:
        return pd.DataFrame(data.X, columns=data.feature_names)

    def fit(self, train: TabularData, validation: TabularData) -> TrainingResult:
        if train.feature_names != validation.feature_names:
            raise ValueError("train and validation feature names differ")
        if not len(train.y) or not len(validation.y):
            raise ValueError("train and validation must both contain samples")
        started = time.perf_counter()
        self.feature_names = train.feature_names
        self.model.fit(
            self._frame(train), train.y,
            eval_set=[(self._frame(validation), validation.y)],
            verbose=self.config.verbose_eval if self.config.verbose_eval > 0 else False,
        )
        history = self.model.evals_result().get("validation_0", {}).get("mae", [])
        best_iteration = getattr(self.model, "best_iteration", len(history) - 1)
        best_score = getattr(self.model, "best_score", min(history))
        print(
            f"[xgboost] finished: best_round={int(best_iteration) + 1}, "
            f"best_validation_mae={float(best_score):.8f}, "
            f"rounds_run={len(history)}",
            flush=True,
        )
        return TrainingResult(
            best_epoch=int(best_iteration),
            best_validation_mae=float(best_score),
            history=tuple({"epoch": float(i), "validation_mae": float(value)} for i, value in enumerate(history)),
            duration_seconds=time.perf_counter() - started,
        )

    def predict(self, data: TabularData) -> np.ndarray:
        if self.feature_names and data.feature_names != self.feature_names:
            raise ValueError("prediction feature names/order do not match the fitted model")
        result = np.asarray(self.model.predict(self._frame(data)), dtype=np.float64)
        if result.shape != (len(data.y),) or not np.isfinite(result).all():
            raise ValueError("XGBoost produced invalid predictions")
        return result

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.model.save_model(path)

    @classmethod
    def load(
        cls, path: Path, config: XGBoostConfig | None = None,
        feature_names: tuple[str, ...] = (),
    ) -> XGBoostForecastModel:
        wrapper = cls(config)
        wrapper.model.load_model(path)
        wrapper.feature_names = feature_names
        return wrapper
