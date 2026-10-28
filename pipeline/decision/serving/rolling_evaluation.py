"""Causal recent-history evaluation using one frozen serving bundle."""
from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.decision.data.input_adapters import SequenceInputAdapter
from pipeline.decision.data.sample_index import SampleIndexBuilder
from pipeline.decision.evaluation.metrics import compute_direction_metrics, compute_metrics
from pipeline.decision.serving.daily_forecast_service import build_daily_features
from pipeline.decision.serving.model_bundle import ForecastModelBundle


def _pinball(actual: np.ndarray, predicted: np.ndarray, quantile: float) -> float:
    error = actual - predicted
    return float(np.mean(np.maximum(quantile * error, (quantile - 1) * error)))


class RollingEvaluationService:
    def __init__(self, device: str = "cpu", batch_size: int = 256):
        self.device = device
        self.batch_size = batch_size

    def _predict_quantiles(
        self, bundle: ForecastModelBundle, matrix: np.ndarray
    ) -> np.ndarray:
        import torch

        outputs = []
        bundle.model.to(self.device)
        bundle.model.eval()
        with torch.no_grad():
            for offset in range(0, len(matrix), self.batch_size):
                tensor = torch.as_tensor(
                    matrix[offset:offset + self.batch_size],
                    dtype=torch.float32,
                    device=self.device,
                )
                outputs.append(bundle.model.forward_quantiles(tensor).cpu().numpy())
        if not outputs:
            return np.empty((0, 3), dtype=np.float64)
        values = np.concatenate(outputs, axis=0).astype(np.float64)
        for column in range(3):
            values[:, column] = bundle.target_scaler.inverse_transform(values[:, column])
        if not np.isfinite(values).all() or not (
            (values[:, 0] <= values[:, 1]) & (values[:, 1] <= values[:, 2])
        ).all():
            raise ValueError("rolling evaluation produced invalid quantiles")
        return values

    def evaluate(
        self,
        bundle: ForecastModelBundle,
        daily_candles: pd.DataFrame,
        days: int,
        daily_cutoff,
    ) -> dict:
        target, features = build_daily_features(daily_candles, bundle)
        samples = SampleIndexBuilder().build(
            target,
            features,
            lookback=bundle.lookback_periods,
            horizon=int(bundle.manifest["horizon_periods"]),
            frequency="1d",
        )
        cutoff = pd.Timestamp(daily_cutoff)
        selected = samples[
            samples["is_valid"]
            & (pd.to_datetime(samples["target_time"], utc=True) < cutoff)
        ].sort_values("target_time").tail(days).reset_index(drop=True)
        if selected.empty:
            raise ValueError("no realized causal samples are available for rolling evaluation")
        adapter = SequenceInputAdapter(features, bundle.scaler)
        matrix = np.stack([
            adapter.transform_one(row)
            for _, row in selected.iterrows()
        ]).astype(np.float32)
        quantiles = self._predict_quantiles(bundle, matrix)
        actual = selected["target_log_return"].to_numpy(dtype=np.float64)
        reference = selected["reference_close_usdt"].to_numpy(dtype=np.float64)
        q10, q50, q90 = quantiles.T
        zero_mae = float(np.mean(np.abs(actual)))
        metrics = compute_metrics(actual, q50, reference, zero_mae)
        direction = compute_direction_metrics(actual, q50)
        return {
            "kind": "rolling_backtest",
            "causal": True,
            "prospective": False,
            "sample_count": len(selected),
            "requested_days": days,
            "first_target_day": pd.Timestamp(selected.iloc[0]["target_time"]).isoformat(),
            "last_target_day": pd.Timestamp(selected.iloc[-1]["target_time"]).isoformat(),
            "mae_return": metrics.mae_return,
            "rmse_return": metrics.rmse_return,
            "mae_price_usdt": metrics.mae_price_usdt,
            "directional_accuracy": direction.accuracy,
            "balanced_accuracy": direction.balanced_accuracy,
            "mcc": direction.mcc,
            "actual_up_rate": direction.actual_up_rate,
            "predicted_up_rate": direction.predicted_up_rate,
            "zero_return_mae": zero_mae,
            "relative_mae": metrics.relative_mae,
            "q10_q90_nominal_coverage": 0.8,
            "q10_q90_empirical_coverage": float(
                ((actual >= q10) & (actual <= q90)).mean()
            ),
            "mean_interval_width": float(np.mean(q90 - q10)),
            "pinball_loss_q10": _pinball(actual, q10, 0.1),
            "pinball_loss_q50": _pinball(actual, q50, 0.5),
            "pinball_loss_q90": _pinball(actual, q90, 0.9),
            "limitations": [
                "retrospective recent-history diagnostic; not prospective performance",
                "the frozen model may have been tuned after seeing some dates in this window",
                "warehouse rows are not point-in-time historical snapshots",
            ],
        }
