"""Daily feature preparation and one-step quantile inference."""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from pipeline.decision.data.feature_extractor import MultiAssetFeatureFusion, feature_extractor
from pipeline.decision.serving.model_bundle import ForecastModelBundle


def split_target_context(
    candles: pd.DataFrame, bundle: ForecastModelBundle
) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = candles.copy()
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True)
    target = frame[frame["symbol"].eq(bundle.symbol)].sort_values("open_time")
    context = frame[~frame["symbol"].eq(bundle.symbol)].sort_values(
        ["symbol", "open_time"]
    )
    if target.empty:
        raise ValueError(f"daily candles contain no target rows for {bundle.symbol}")
    return target.reset_index(drop=True), context.reset_index(drop=True)


def build_daily_features(
    candles: pd.DataFrame, bundle: ForecastModelBundle
) -> tuple[pd.DataFrame, pd.DataFrame]:
    target, context = split_target_context(candles, bundle)
    target_features = feature_extractor(bundle.feature_version).transform(target)
    features = MultiAssetFeatureFusion().attach(
        target_features,
        context,
        bundle.symbol,
        bundle.required_symbols()[1:],
        bundle.feature_version,
    )
    if tuple(bundle.scaler.feature_names) != tuple(bundle.manifest["feature_names"]):
        raise ValueError("runtime feature layout differs from serving bundle")
    return target, features


class DailyForecastService:
    def __init__(self, device: str = "cpu"):
        self.device = device

    def predict(
        self, bundle: ForecastModelBundle, daily_candles: pd.DataFrame
    ) -> dict:
        target, context = split_target_context(daily_candles, bundle)
        prediction, batch_ids = bundle.build_predictor(self.device).predict(
            target, context_candles=context
        )
        if None in (prediction.return_q10, prediction.return_q50, prediction.return_q90):
            raise ValueError("served daily model does not produce quantiles")
        q10, q50, q90 = (
            float(prediction.return_q10),
            float(prediction.return_q50),
            float(prediction.return_q90),
        )
        if not q10 <= q50 <= q90:
            raise ValueError("model quantiles crossed after inverse scaling")
        reference = float(prediction.reference_close_usdt)
        target_open = pd.Timestamp(prediction.target_time)
        target_close = target_open + pd.Timedelta(days=1)
        return {
            "target_open": target_open.isoformat(),
            "target_close": target_close.isoformat(),
            "reference_open_time": (target_open - pd.Timedelta(days=1)).isoformat(),
            "reference_close_usdt": reference,
            "return_q10": q10,
            "return_q50": q50,
            "return_q90": q90,
            "predicted_close_q10_usdt": float(reference * np.exp(q10)),
            "predicted_close_q50_usdt": float(reference * np.exp(q50)),
            "predicted_close_q90_usdt": float(reference * np.exp(q90)),
            "predicted_move_pct": float(np.expm1(q50) * 100),
            "direction": "up" if q50 > 0 else "down" if q50 < 0 else "flat",
            "interval_crosses_zero": bool(q10 <= 0 <= q90),
            "interval_width": q90 - q10,
            "quantile_interpretation": (
                "empirical interval; not a guaranteed probability interval"
            ),
            "direction_probability_up": prediction.direction_probability_up,
            "batch_ids": list(batch_ids),
        }
