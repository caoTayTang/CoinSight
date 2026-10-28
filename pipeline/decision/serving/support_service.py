"""Orchestrate readiness, daily inference and bounded support diagnostics."""
from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from pipeline.decision.data.warehouse_repository import (
    DailyCandleRepository,
    HourlyCandleRepository,
)
from pipeline.decision.serving.contracts import ForecastSupportRequest
from pipeline.decision.serving.daily_forecast_service import DailyForecastService
from pipeline.decision.serving.data_readiness import ForecastDataReadinessService
from pipeline.decision.serving.market_statistics import MarketStatisticsService
from pipeline.decision.serving.model_bundle import ForecastModelBundle
from pipeline.decision.serving.rolling_evaluation import RollingEvaluationService
from pipeline.decision.serving.targeted_sync import TargetedBackfillService


def _finite(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(item) for item in value]
    if isinstance(value, (float, np.floating)):
        if not np.isfinite(value):
            raise ValueError("support response contains a non-finite number")
        return float(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


class ForecastSupportService:
    def __init__(
        self,
        *,
        bundle_root: Path | str | None = None,
        daily_repository=None,
        hourly_repository=None,
        readiness_service: ForecastDataReadinessService | None = None,
        device: str = "cpu",
        now_fn=None,
    ):
        self.bundle_root = Path(bundle_root or os.getenv(
            "DAILY_FORECAST_BUNDLE_ROOT", "data/models/daily-forecast"
        ))
        self.daily = daily_repository or DailyCandleRepository()
        self.hourly = hourly_repository or HourlyCandleRepository()
        self.now_fn = now_fn or (lambda: datetime.now(UTC))
        if readiness_service is None:
            syncer = TargetedBackfillService()
            readiness_service = ForecastDataReadinessService(
                self.daily, self.hourly, syncer, now_fn=self.now_fn
            )
        self.readiness = readiness_service
        self.daily_forecast = DailyForecastService(device)
        self.rolling = RollingEvaluationService(device)
        self.statistics = MarketStatisticsService()

    @lru_cache(maxsize=2)
    def _bundle(self, symbol: str) -> ForecastModelBundle:
        return ForecastModelBundle.load(symbol, root=self.bundle_root)

    def report(
        self,
        symbol: str = "BTC",
        performance_days: int = 30,
        market_days: int = 30,
        trend_hours: int = 168,
        cutoff: str | None = None,
    ) -> dict:
        observed_at = self.now_fn().astimezone(UTC).isoformat()
        try:
            request = ForecastSupportRequest(
                symbol=symbol,
                performance_days=performance_days,
                market_days=market_days,
                trend_hours=trend_hours,
                cutoff=cutoff,
            )
        except Exception as error:
            return {
                "status": "unavailable",
                "observed_at": observed_at,
                "symbol": str(symbol).upper(),
                "reason": "invalid_request",
                "error_type": type(error).__name__,
                "detail": str(error),
            }
        try:
            bundle = self._bundle(request.symbol)
        except FileNotFoundError:
            return {
                "status": "unavailable",
                "observed_at": observed_at,
                "symbol": request.symbol,
                "reason": "no_pinned_model_bundle",
            }
        except Exception as error:
            return {
                "status": "unavailable",
                "observed_at": observed_at,
                "symbol": request.symbol,
                "reason": "invalid_model_bundle",
                "error_type": type(error).__name__,
            }
        try:
            requirements, readiness = self.readiness.ensure_ready(bundle, request)
            if not readiness.is_complete:
                return _finite({
                    "status": "insufficient_data",
                    "observed_at": observed_at,
                    "symbol": request.symbol,
                    "reason": readiness.backfill_reason,
                    "data_readiness": readiness.to_dict(),
                    "model": self._model_summary(bundle),
                    "limitations": [
                        "forecast was not run because the exact required warehouse grid is incomplete"
                    ],
                })
            daily = self.daily.fetch_candles_many(
                requirements.required_daily_symbols,
                requirements.daily_range.start,
                requirements.daily_range.end,
            )
            hourly = self.hourly.fetch_candles(
                request.symbol,
                requirements.hourly_range.start,
                requirements.hourly_range.end,
            )
            target_daily = daily[daily["symbol"].astype(str).str.upper().eq(request.symbol)]
            forecast = self.daily_forecast.predict(bundle, daily)
            performance = self.rolling.evaluate(
                bundle, daily, request.performance_days, requirements.daily_cutoff
            )
            market = self.statistics.daily_statistics(target_daily, request.market_days)
            trend = self.statistics.hourly_trend(hourly, request.trend_hours)
            daily_batch_ids = sorted(int(value) for value in daily["batch_id"].dropna().unique())
            hourly_batch_ids = sorted(int(value) for value in hourly["batch_id"].dropna().unique())
            response = {
                "status": "ready",
                "observed_at": observed_at,
                "symbol": request.symbol,
                "forecast": forecast,
                "recent_performance": performance,
                "market_statistics": market,
                "hourly_trend": trend,
                "data_readiness": readiness.to_dict(),
                "data_freshness": {
                    "source_code": "binance",
                    "last_closed_daily_open": pd.Timestamp(
                        target_daily["open_time"].max()
                    ).isoformat(),
                    "expected_last_daily_open": (
                        pd.Timestamp(requirements.daily_cutoff) - pd.Timedelta(days=1)
                    ).isoformat(),
                    "last_closed_hourly_open": pd.Timestamp(
                        hourly["open_time"].max()
                    ).isoformat(),
                    "expected_last_hourly_open": (
                        pd.Timestamp(requirements.hourly_cutoff) - pd.Timedelta(hours=1)
                    ).isoformat(),
                },
                "lineage": {
                    "daily_warehouse_batch_ids": daily_batch_ids,
                    "hourly_warehouse_batch_ids": hourly_batch_ids,
                    "extract_batch_ids": list(readiness.extract_batch_ids),
                    "load_batch_ids": list(readiness.load_batch_ids),
                },
                "model": self._model_summary(bundle),
                "limitations": [
                    "research support signal; not a trading instruction",
                    "q10-q90 is an empirical model interval, not guaranteed confidence",
                    "recent performance is retrospective and may overlap model-development dates",
                    "MAE and direction can disagree; both are reported",
                ],
            }
            return _finite(response)
        except Exception as error:
            return {
                "status": "unavailable",
                "observed_at": observed_at,
                "symbol": request.symbol,
                "reason": "support_pipeline_failed",
                "error_type": type(error).__name__,
                "detail": str(error)[:500],
                "model": self._model_summary(bundle),
            }

    @staticmethod
    def _model_summary(bundle: ForecastModelBundle) -> dict:
        manifest = bundle.manifest
        checksums = json.loads(
            (bundle.directory / "artifact_checksums.json").read_text(encoding="utf-8")
        )
        return {
            "model_id": manifest["model_id"],
            "model_version": manifest["model_version"],
            "run_id": manifest["run_id"],
            "symbol": manifest["symbol"],
            "model_type": manifest["model_type"],
            "feature_version": manifest["feature_version"],
            "frequency": manifest["frequency"],
            "lookback_periods": manifest["lookback_periods"],
            "horizon_periods": manifest["horizon_periods"],
            "asset_order": manifest["asset_order"],
            "snapshot_id": manifest["snapshot_id"],
            "seed": manifest["seed"],
            "deployment_tier": manifest["deployment_tier"],
            "validation_decision": manifest.get("validation_decision"),
            "artifact_checksums": checksums,
        }


@lru_cache(maxsize=1)
def default_support_service() -> ForecastSupportService:
    return ForecastSupportService()


def forecast_support(**kwargs) -> dict:
    return default_support_service().report(**kwargs)
