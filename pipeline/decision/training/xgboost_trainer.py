"""Training adapter that prevents XGBoost from reading the test split."""
from __future__ import annotations

from pipeline.decision.data.dataloader import ForecastDataModule
from pipeline.decision.models.xgboost_regressor import XGBoostForecastModel
from pipeline.decision.types import DatasetSplit, TrainingResult


class XGBoostTrainer:
    def fit(
        self, model: XGBoostForecastModel, data: ForecastDataModule
    ) -> TrainingResult:
        return model.fit(
            data.tabular(DatasetSplit.TRAIN),
            data.tabular(DatasetSplit.VALIDATION),
        )

    def predict(
        self, model: XGBoostForecastModel, data: ForecastDataModule, split: DatasetSplit
    ):
        return model.predict(data.tabular(split))
