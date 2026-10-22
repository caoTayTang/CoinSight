"""Construct only model architectures whose implementation is approved."""
from __future__ import annotations

from pipeline.decision.config import RecurrentConfig, XGBoostConfig
from pipeline.decision.types import ModelType


def build_model(model_type: ModelType | str, config=None):
    resolved = ModelType.parse(model_type)
    if resolved is ModelType.XGBOOST:
        from pipeline.decision.models.xgboost_regressor import XGBoostForecastModel
        return XGBoostForecastModel(config or XGBoostConfig())
    if resolved in {ModelType.GRU, ModelType.LSTM}:
        from pipeline.decision.models.recurrent_regressor import (
            GRURegressor,
            LSTMRegressor,
        )
        recurrent = config or RecurrentConfig()
        kwargs = {
            "input_size": recurrent.input_size,
            "hidden_size": recurrent.hidden_size,
            "num_layers": recurrent.num_layers,
            "dropout": recurrent.dropout,
            "separate_direction_head": recurrent.separate_direction_head,
            "quantile_output": recurrent.quantile_output,
        }
        return GRURegressor(**kwargs) if resolved is ModelType.GRU else LSTMRegressor(**kwargs)
    raise NotImplementedError(
        f"{resolved.value} model definition is reserved for the Transformer phase"
    )
