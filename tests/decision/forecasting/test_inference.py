import numpy as np
import pandas as pd
import pytest

from pipeline.decision.data.feature_extractor import (
    BASE_FEATURES,
    fused_sequence_feature_names,
)
from pipeline.decision.data.scaler import SequenceScaler, TargetScaler
from pipeline.decision.inference.predictor import ForecastPredictor
from pipeline.decision.types import ModelType
from tests.decision.forecasting.helpers import candles


class ConstantModel:
    def predict(self, tabular):
        assert tabular.X.shape == (1, 78)
        return np.asarray([0.01])


def test_xgboost_inference_uses_169_closed_candles_and_next_hour_target():
    frame = candles(169)
    predictor = ForecastPredictor(ConstantModel(), ModelType.XGBOOST, "run-1")

    result, batch_ids = predictor.predict(frame)

    assert result.symbol == "BTC"
    assert result.target_time == (frame.open_time.iloc[-1] + pd.Timedelta(hours=1)).to_pydatetime()
    assert result.predicted_log_return == 0.01
    assert result.predicted_close_usdt == frame.close_price.iloc[-1] * np.exp(0.01)
    assert batch_ids == (1,)


def test_sequence_inference_inverse_transforms_standardized_target():
    torch = pytest.importorskip("torch")

    class ConstantSequenceModel(torch.nn.Module):
        def forward(self, inputs):
            return torch.full((len(inputs), 1), 2.0, device=inputs.device)

    feature_scaler = SequenceScaler(BASE_FEATURES)
    feature_scaler.mean_ = np.zeros(len(BASE_FEATURES), dtype=np.float64)
    feature_scaler.scale_ = np.ones(len(BASE_FEATURES), dtype=np.float64)
    target_scaler = TargetScaler().fit(np.asarray([-0.01, 0.01]))
    frame = candles(169)
    predictor = ForecastPredictor(
        ConstantSequenceModel(), ModelType.GRU, "run-1",
        scaler=feature_scaler, target_scaler=target_scaler,
    )

    result, _ = predictor.predict(frame)

    assert np.isclose(result.predicted_log_return, 0.02)
    assert np.isclose(
        result.predicted_close_usdt,
        frame.close_price.iloc[-1] * np.exp(0.02),
    )
    assert result.direction_probability_up is None


def test_two_head_sequence_inference_returns_direction_probability():
    pytest.importorskip("torch")
    from pipeline.decision.models.recurrent_regressor import GRURegressor

    feature_scaler = SequenceScaler(BASE_FEATURES)
    feature_scaler.mean_ = np.zeros(len(BASE_FEATURES), dtype=np.float64)
    feature_scaler.scale_ = np.ones(len(BASE_FEATURES), dtype=np.float64)
    target_scaler = TargetScaler().fit(np.asarray([-0.01, 0.01]))
    predictor = ForecastPredictor(
        GRURegressor(
            hidden_size=4, dropout=0,
            quantile_output=False, separate_direction_head=True,
        ),
        ModelType.GRU,
        "two-head-run",
        scaler=feature_scaler,
        target_scaler=target_scaler,
    )

    result, _ = predictor.predict(candles(169))

    assert result.direction_probability_up is not None
    assert 0.0 <= result.direction_probability_up <= 1.0


def test_quantile_sequence_inference_returns_interval_and_confidence():
    pytest.importorskip("torch")
    from pipeline.decision.models.recurrent_regressor import GRURegressor

    feature_scaler = SequenceScaler(BASE_FEATURES)
    feature_scaler.mean_ = np.zeros(len(BASE_FEATURES), dtype=np.float64)
    feature_scaler.scale_ = np.ones(len(BASE_FEATURES), dtype=np.float64)
    target_scaler = TargetScaler().fit(np.asarray([-0.01, 0.01]))
    predictor = ForecastPredictor(
        GRURegressor(hidden_size=4, dropout=0), ModelType.GRU, "quantile-run",
        scaler=feature_scaler, target_scaler=target_scaler,
    )

    result, _ = predictor.predict(candles(169))

    assert result.return_q10 <= result.return_q50 <= result.return_q90
    assert result.predicted_log_return == result.return_q50
    assert result.direction_probability_up is not None
    assert 0.0 <= result.direction_probability_up <= 1.0
    assert result.forecast_confidence in {
        "confident_up", "confident_down", "uncertain"
    }


def test_v2_sequence_inference_requires_and_fuses_cross_asset_context():
    torch = pytest.importorskip("torch")

    class ShapeCheckingModel(torch.nn.Module):
        def forward(self, inputs):
            assert tuple(inputs.shape[1:]) == (336, 81)
            return torch.zeros((len(inputs), 1), device=inputs.device)

    names = fused_sequence_feature_names("BTC", ("ETH", "SOL"))
    scaler = SequenceScaler(names)
    scaler.mean_ = np.zeros(len(names), dtype=np.float64)
    scaler.scale_ = np.ones(len(names), dtype=np.float64)
    target = candles(672)
    context_frames = []
    for symbol, multiplier in (("ETH", 1.1), ("SOL", 0.9)):
        frame = candles(672).copy()
        frame["symbol"] = symbol
        for column in ("open_price", "high_price", "low_price", "close_price"):
            frame[column] *= multiplier
        context_frames.append(frame)
    context = pd.concat(context_frames, ignore_index=True)
    predictor = ForecastPredictor(
        ShapeCheckingModel(),
        ModelType.GRU,
        "run-v2",
        scaler=scaler,
        lookback=336,
        context_symbols=("BTC", "ETH", "SOL"),
    )

    with pytest.raises(ValueError, match="requires context candles"):
        predictor.predict(target)
    result, _ = predictor.predict(target, context)

    assert result.symbol == "BTC"
    assert result.predicted_log_return == 0.0


def test_v2_target_only_inference_does_not_require_context_candles():
    torch = pytest.importorskip("torch")

    class ShapeCheckingModel(torch.nn.Module):
        def forward(self, inputs):
            assert tuple(inputs.shape[1:]) == (336, 27)
            return torch.zeros((len(inputs), 1), device=inputs.device)

    names = fused_sequence_feature_names("BTC", ("BTC",))
    scaler = SequenceScaler(names)
    scaler.mean_ = np.zeros(len(names), dtype=np.float64)
    scaler.scale_ = np.ones(len(names), dtype=np.float64)
    predictor = ForecastPredictor(
        ShapeCheckingModel(),
        ModelType.GRU,
        "run-v2-target-only",
        scaler=scaler,
        context_symbols=("BTC",),
    )

    result, _ = predictor.predict(candles(672))

    assert result.symbol == "BTC"
    assert result.predicted_log_return == 0.0
