"""Build one leakage-safe live input and produce a period forecast."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from pipeline.decision.data.feature_extractor import (
    DAILY_SEQUENCE_FEATURES,
    MAX_ROLLING_WINDOW,
    V1_SEQUENCE_FEATURES,
    MultiAssetFeatureFusion,
    feature_extractor,
    feature_warmup_periods,
    fused_symbols_from_feature_names,
    is_fused_feature_version,
)
from pipeline.decision.data.input_adapters import (
    PatchTSTInputAdapter,
    SequenceInputAdapter,
    XGBoostInputAdapter,
)
from pipeline.decision.data.scaler import SequenceScaler, TargetScaler
from pipeline.decision.types import ModelType, PredictionResult, TabularData


@dataclass(frozen=True)
class InferenceInputs:
    model_type: ModelType
    target_time: datetime
    reference_close_usdt: float
    batch_ids: tuple[int, ...]
    tabular: TabularData | None = None
    sequence: np.ndarray | None = None


class InferenceInputBuilder:
    def __init__(self, lookback: int = 168):
        self.lookback = lookback

    def build(
        self,
        candles: pd.DataFrame,
        model_type: ModelType | str,
        scaler: SequenceScaler | None = None,
        context_candles: pd.DataFrame | None = None,
        context_symbols: tuple[str, ...] | list[str] | None = None,
        feature_version: str | None = None,
        frequency: str = "1h",
    ) -> InferenceInputs:
        resolved = ModelType.parse(model_type)
        feature_version = feature_version or "hourly-return-v1"
        fused_symbols: tuple[str, ...] = ()
        if resolved is not ModelType.XGBOOST and scaler is not None:
            if (
                feature_version == "hourly-return-v1"
                and scaler.feature_names != V1_SEQUENCE_FEATURES
            ):
                feature_version = "hourly-return-v2"
            elif (
                feature_version == "daily-return-v1"
                and scaler.feature_names != DAILY_SEQUENCE_FEATURES
            ):
                feature_version = "daily-return-v2"
            if is_fused_feature_version(feature_version):
                fused_symbols = fused_symbols_from_feature_names(
                    scaler.feature_names, feature_version
                )
        if resolved is ModelType.XGBOOST and is_fused_feature_version(feature_version):
            raise ValueError(
                f"{feature_version} multi-asset inputs are currently supported "
                "by sequence models only"
            )
        expected_frequency = "1d" if feature_version.startswith("daily-") else "1h"
        if frequency != expected_frequency:
            raise ValueError("inference frequency does not match feature version")
        step = pd.Timedelta(days=1) if frequency == "1d" else pd.Timedelta(hours=1)
        warmup = feature_warmup_periods(feature_version)
        required = self.lookback + warmup
        if len(candles) < required:
            raise ValueError(
                f"inference requires at least {required} closed {frequency} candles"
            )
        raw = candles.sort_values("open_time").tail(required).reset_index(drop=True)
        times = pd.to_datetime(raw["open_time"], utc=True)
        if not times.diff().dropna().eq(step).all():
            raise ValueError("inference input contains a candle continuity gap")
        features = feature_extractor(feature_version).transform(raw)
        if is_fused_feature_version(feature_version):
            target_symbol = str(raw.iloc[-1]["symbol"]).upper()
            if not fused_symbols or fused_symbols[0] != target_symbol:
                raise ValueError("v2 scaler target symbol does not match inference candles")
            expected_context = fused_symbols[1:]
            if expected_context and (context_candles is None or context_candles.empty):
                raise ValueError(
                    f"{feature_version} inference requires context candles"
                )
            if context_symbols is not None:
                configured = {
                    str(symbol).upper() for symbol in context_symbols
                    if str(symbol).upper() != target_symbol
                }
                if configured != set(expected_context):
                    raise ValueError("inference context symbols do not match the training scaler")
            features = MultiAssetFeatureFusion().attach(
                features,
                context_candles,
                target_symbol,
                expected_context,
                feature_version,
            )
        window = features.tail(self.lookback)
        if len(window) != self.lookback or not window["feature_valid"].all():
            raise ValueError("inference input contains invalid candles or features")
        input_time = times.iloc[-1]
        target_time = input_time + step
        reference = float(raw.iloc[-1]["close_price"])
        sample = pd.DataFrame([{
            "sample_id": f"{raw.iloc[-1]['symbol']}:{target_time.isoformat()}",
            "symbol": str(raw.iloc[-1]["symbol"]).upper(),
            "window_start_time": pd.to_datetime(window.iloc[0]["open_time"], utc=True),
            "latest_input_open_time": input_time,
            "cutoff_time": target_time,
            "target_time": target_time,
            "window_start_row": int(window.iloc[0]["row_number"]),
            "window_end_row": int(window.iloc[-1]["row_number"]),
            "target_row": -1,
            "reference_close_usdt": reference,
            "actual_close_usdt": np.nan,
            "target_log_return": 0.0,
            "is_valid": True,
            "rejection_reason": None,
        }])
        batch_values = set(raw["batch_id"].dropna())
        if context_candles is not None and "batch_id" in context_candles:
            batch_values.update(context_candles["batch_id"].dropna())
        batch_ids = tuple(sorted(int(value) for value in batch_values))
        if resolved is ModelType.XGBOOST:
            tabular = XGBoostInputAdapter(feature_version).transform(features, sample)
            return InferenceInputs(resolved, target_time.to_pydatetime(), reference, batch_ids, tabular=tabular)
        if scaler is None:
            raise ValueError("sequence inference requires the training scaler")
        adapter_class = PatchTSTInputAdapter if resolved is ModelType.PATCHTST else SequenceInputAdapter
        adapter = adapter_class(features, scaler)
        sequence = adapter.layout(adapter.transform_one(sample.iloc[0]))[None, ...]
        return InferenceInputs(
            resolved, target_time.to_pydatetime(), reference, batch_ids, sequence=sequence
        )


class ForecastPredictor:
    def __init__(
        self,
        model,
        model_type: ModelType | str,
        run_id: str,
        scaler: SequenceScaler | None = None,
        target_scaler: TargetScaler | None = None,
        device: str = "cpu",
        lookback: int | None = None,
        context_symbols: tuple[str, ...] | list[str] | None = None,
        feature_version: str = "hourly-return-v1",
        frequency: str = "1h",
    ):
        self.model = model
        self.model_type = ModelType.parse(model_type)
        self.run_id = run_id
        self.scaler = scaler
        self.target_scaler = target_scaler
        self.device = device
        self.feature_version = feature_version
        self.frequency = frequency
        self.lookback = lookback if lookback is not None else (
            90 if frequency == "1d" else (
                MAX_ROLLING_WINDOW
                if scaler is not None and scaler.feature_names != V1_SEQUENCE_FEATURES
                else 168
            )
        )
        self.context_symbols = None if context_symbols is None else tuple(context_symbols)

    def predict(
        self,
        candles: pd.DataFrame,
        context_candles: pd.DataFrame | None = None,
    ) -> tuple[PredictionResult, tuple[int, ...]]:
        inputs = InferenceInputBuilder(self.lookback).build(
            candles,
            self.model_type,
            self.scaler,
            context_candles=context_candles,
            context_symbols=self.context_symbols,
            feature_version=self.feature_version,
            frequency=self.frequency,
        )
        direction_probability_up = None
        return_q10 = return_q50 = return_q90 = None
        forecast_confidence = None
        if self.model_type is ModelType.XGBOOST:
            predicted = float(self.model.predict(inputs.tabular)[0])
        else:
            try:
                import torch
            except ImportError as error:
                raise RuntimeError("PyTorch is required for sequence inference") from error
            self.model.to(self.device)
            self.model.eval()
            with torch.no_grad():
                tensor = torch.as_tensor(inputs.sequence, dtype=torch.float32, device=self.device)
                forward_heads = getattr(self.model, "forward_heads", None)
                if getattr(self.model, "quantile_output", False):
                    quantile_tensor = self.model.forward_quantiles(tensor)
                    quantiles = quantile_tensor.detach().cpu().numpy().reshape(-1, 3)[0]
                    if self.target_scaler is not None:
                        quantiles = np.asarray([
                            self.target_scaler.inverse_transform([value])[0]
                            for value in quantiles
                        ])
                    return_q10, return_q50, return_q90 = map(float, quantiles)
                    predicted = return_q50
                    forecast_confidence = (
                        "confident_up" if return_q10 > 0 else
                        "confident_down" if return_q90 < 0 else
                        "uncertain"
                    )
                    predicted_tensor = None
                elif (
                    callable(forward_heads)
                    and getattr(self.model, "separate_direction_head", False)
                ):
                    predicted_tensor, direction_logits = forward_heads(tensor)
                    if direction_logits is None:
                        raise ValueError("two-head model did not return direction logits")
                    direction_probability_up = float(
                        torch.sigmoid(direction_logits).detach().cpu().reshape(-1)[0]
                    )
                else:
                    predicted_tensor = self.model(tensor)
                if predicted_tensor is not None:
                    predicted = float(predicted_tensor.detach().cpu().reshape(-1)[0])
            if self.target_scaler is not None and return_q50 is None:
                predicted = float(self.target_scaler.inverse_transform([predicted])[0])
        if not np.isfinite(predicted):
            raise ValueError("model produced a non-finite forecast")
        symbol = str(candles.sort_values("open_time").iloc[-1]["symbol"]).upper()
        result = PredictionResult(
            symbol=symbol,
            target_time=inputs.target_time,
            reference_close_usdt=inputs.reference_close_usdt,
            predicted_log_return=predicted,
            predicted_close_usdt=float(inputs.reference_close_usdt * np.exp(predicted)),
            model_type=self.model_type,
            run_id=self.run_id,
            direction_probability_up=direction_probability_up,
            return_q10=return_q10,
            return_q50=return_q50,
            return_q90=return_q90,
            forecast_confidence=forecast_confidence,
        )
        return result, inputs.batch_ids
