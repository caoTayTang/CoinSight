"""Build causal historical support observations and run the paper policy."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from pipeline.decision.data.warehouse_repository import (
    DailyCandleRepository,
    HourlyCandleRepository,
)
from pipeline.decision.serving.contracts import DataRequirements, ForecastSupportRequest
from pipeline.decision.serving.data_readiness import ForecastDataReadinessService
from pipeline.decision.serving.model_bundle import ForecastModelBundle
from pipeline.decision.serving.support_service import ForecastSupportService
from pipeline.decision.serving.targeted_sync import TargetedBackfillService
from pipeline.decision.types import TimeRange, utc_datetime

from .backtest import BacktestObservation, PolicyBacktester


class _FrameCandleRepository:
    """Read-only repository over one prefetched frame."""

    def __init__(self, frame: pd.DataFrame):
        self.frame = frame.copy()
        self.frame["symbol"] = self.frame["symbol"].astype(str).str.upper()
        self.frame["open_time"] = pd.to_datetime(self.frame["open_time"], utc=True)

    def fetch_candles(self, symbol, start, end) -> pd.DataFrame:
        return self.fetch_candles_many((symbol,), start, end).reset_index(drop=True)

    def fetch_candles_many(self, symbols, start, end) -> pd.DataFrame:
        wanted = {str(symbol).upper() for symbol in symbols}
        start, end = pd.Timestamp(utc_datetime(start)), pd.Timestamp(utc_datetime(end))
        selected = self.frame[
            self.frame["symbol"].isin(wanted)
            & self.frame["open_time"].ge(start)
            & self.frame["open_time"].lt(end)
        ]
        return selected.sort_values(["symbol", "open_time"]).reset_index(drop=True).copy()


@dataclass(frozen=True)
class BacktestWindow:
    start: datetime
    end: datetime
    snapshot_test_start: datetime
    snapshot_test_end: datetime
    snapshot_id: str
    uses_only_snapshot_test_split: bool
    includes_post_test_period: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start.isoformat(),
            "end_exclusive": self.end.isoformat(),
            "snapshot_test_start": self.snapshot_test_start.isoformat(),
            "snapshot_test_end_exclusive": self.snapshot_test_end.isoformat(),
            "snapshot_id": self.snapshot_id,
            "uses_only_snapshot_test_split": self.uses_only_snapshot_test_split,
            "includes_post_test_period": self.includes_post_test_period,
        }


def resolve_backtest_window(
    bundle: ForecastModelBundle,
    snapshot_root: str | Path,
    *,
    start: datetime | str | None = None,
    end: datetime | str | None = None,
    allow_outside_test: bool = False,
) -> BacktestWindow:
    snapshot_id = str(bundle.manifest["snapshot_id"])
    path = Path(snapshot_root) / snapshot_id / bundle.symbol / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"snapshot manifest is required for a causal backtest: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    boundaries = manifest.get("split_boundaries", {})
    test_start = utc_datetime(boundaries["test_start"])
    test_end = utc_datetime(boundaries["test_end"])
    selected_start = utc_datetime(start) if start is not None else test_start
    selected_end = utc_datetime(end) if end is not None else test_end
    for name, value in (("start", selected_start), ("end", selected_end)):
        if value != pd.Timestamp(value).floor("D").to_pydatetime():
            raise ValueError(f"{name} must be a UTC day boundary (00:00:00)")
    if selected_start >= selected_end:
        raise ValueError("backtest start must be before end")
    within_test = selected_start >= test_start and selected_end <= test_end
    includes_post_test = selected_end > test_end
    if selected_start < test_start and not allow_outside_test:
        raise ValueError(
            "requested period is outside the frozen snapshot test split; "
            "use --allow-outside-test only for an explicitly in-sample diagnostic"
        )
    return BacktestWindow(
        selected_start, selected_end, test_start, test_end, snapshot_id,
        within_test, includes_post_test,
    )


class HistoricalPolicyBacktestRunner:
    """Prefetch warehouse rows once, then replay one causal decision per UTC day."""

    def __init__(
        self,
        policy_config: dict[str, Any],
        *,
        bundle_root: str | Path = "data/models/daily-forecast",
        snapshot_root: str | Path = "data/forecasting/snapshots",
        daily_repository=None,
        hourly_repository=None,
        device: str = "cpu",
    ):
        self.policy_config = dict(policy_config)
        self.bundle_root = Path(bundle_root)
        self.snapshot_root = Path(snapshot_root)
        self.daily = daily_repository or DailyCandleRepository()
        self.hourly = hourly_repository or HourlyCandleRepository()
        self.device = device

    def run(
        self,
        symbol: str,
        *,
        start: datetime | str | None = None,
        end: datetime | str | None = None,
        initial_cash_usdt: float = 100_000.0,
        performance_days: int = 30,
        market_days: int = 30,
        trend_hours: int = 168,
        allow_outside_test: bool = False,
        progress: Callable[[int, int, datetime], None] | None = None,
        stage: Callable[[str], None] | None = None,
    ) -> tuple[dict[str, Any], list[BacktestObservation]]:
        if initial_cash_usdt <= 0:
            raise ValueError("initial cash must be positive")
        bundle = ForecastModelBundle.load(
            symbol, root=self.bundle_root, device=self.device
        )
        # Empty end means all outcomes available through the last fully closed
        # UTC day. It never includes today's still-open daily candle.
        resolved_end = end or pd.Timestamp(datetime.now(UTC)).floor("D").isoformat()
        window = resolve_backtest_window(
            bundle, self.snapshot_root, start=start, end=resolved_end,
            allow_outside_test=allow_outside_test,
        )
        cutoffs = [item.to_pydatetime() for item in pd.date_range(
            window.start, window.end, freq="1D", inclusive="left"
        )]
        request_args = dict(
            symbol=bundle.symbol,
            performance_days=performance_days,
            market_days=market_days,
            trend_hours=trend_hours,
        )
        range_service = ForecastDataReadinessService(
            self.daily, self.hourly, None, now_fn=lambda: window.end
        )
        first_requirements = range_service.required_ranges(
            bundle, ForecastSupportRequest(**request_args, cutoff=cutoffs[0])
        )
        last_requirements = range_service.required_ranges(
            bundle, ForecastSupportRequest(**request_args, cutoff=cutoffs[-1])
        )
        union_requirements = DataRequirements(
            symbol=bundle.symbol,
            daily_cutoff=window.end,
            hourly_cutoff=last_requirements.hourly_cutoff,
            required_daily_symbols=bundle.required_symbols(),
            daily_range=TimeRange(first_requirements.daily_range.start, window.end),
            hourly_range=TimeRange(
                first_requirements.hourly_range.start,
                last_requirements.hourly_range.end,
            ),
        )
        readiness_service = ForecastDataReadinessService(
            self.daily, self.hourly, TargetedBackfillService(),
            now_fn=lambda: window.end,
        )
        if stage is not None:
            stage("checking_warehouse_coverage")
        before_readiness = readiness_service.audit(union_requirements)
        if stage is not None and not before_readiness.is_complete:
            stage("backfilling_missing_ranges")
        grid_readiness = readiness_service.ensure_requirements(union_requirements)
        if not grid_readiness.is_complete:
            raise RuntimeError(
                "backtest warehouse grid remains incomplete after targeted sync: "
                f"{grid_readiness.to_dict()}"
            )
        daily_frame = self.daily.fetch_candles_many(
            bundle.required_symbols(),
            first_requirements.daily_range.start,
            # Include target candles through the exclusive window end only for
            # post-decision scoring. Per-cutoff repositories below still hide
            # these future rows from feature generation and policy evaluation.
            window.end,
        )
        if stage is not None:
            stage("replaying_daily_decisions")
        hourly_frame = self.hourly.fetch_candles(
            bundle.symbol,
            first_requirements.hourly_range.start,
            last_requirements.hourly_range.end,
        )
        memory_daily = _FrameCandleRepository(daily_frame)
        memory_hourly = _FrameCandleRepository(hourly_frame)
        readiness = ForecastDataReadinessService(
            memory_daily, memory_hourly, None, now_fn=lambda: window.end
        )
        support_service = ForecastSupportService(
            bundle_root=self.bundle_root,
            daily_repository=memory_daily,
            hourly_repository=memory_hourly,
            readiness_service=readiness,
            device=self.device,
            now_fn=lambda: window.end,
        )
        observations: list[BacktestObservation] = []
        target_outcomes = daily_frame[
            daily_frame["symbol"].astype(str).str.upper().eq(bundle.symbol)
        ].copy()
        target_outcomes["open_time"] = pd.to_datetime(
            target_outcomes["open_time"], utc=True
        )
        outcome_by_open_time = {
            pd.Timestamp(row.open_time): float(row.close_price)
            for row in target_outcomes.itertuples(index=False)
        }
        for index, cutoff in enumerate(cutoffs, start=1):
            if progress is not None:
                progress(index, len(cutoffs), cutoff)
            support = support_service.report(**request_args, cutoff=cutoff)
            if support.get("status") != "ready":
                raise RuntimeError(
                    f"cannot build causal support at {cutoff.isoformat()}: "
                    f"{support.get('reason', support.get('status'))}; "
                    "backfill the reported warehouse range and retry"
                )
            # The live service's observed_at is wall-clock time. During replay,
            # freeze it to the historical decision cutoff.
            support = dict(support)
            support["observed_at"] = cutoff.astimezone(UTC).isoformat()
            actual_target_close = outcome_by_open_time.get(
                pd.Timestamp(support["forecast"]["target_open"])
            )
            if actual_target_close is None:
                raise RuntimeError(
                    "missing realized target candle for direction/P&L evaluation at "
                    f"{support['forecast']['target_open']}"
                )
            observations.append(BacktestObservation(
                observed_at=cutoff,
                symbol=bundle.symbol,
                market_price_usdt=float(support["forecast"]["reference_close_usdt"]),
                support=support,
                actual_target_close_usdt=actual_target_close,
            ))
        result = PolicyBacktester(self.policy_config).run(
            observations, initial_cash_usdt=initial_cash_usdt
        )
        result["symbol"] = bundle.symbol
        result["model_id"] = bundle.manifest["model_id"]
        result["model_version"] = bundle.manifest["model_version"]
        result["model_run_id"] = bundle.manifest["run_id"]
        result["window"] = window.to_dict()
        result["data_readiness"] = grid_readiness.to_dict()
        result["data_readiness_before_backfill"] = before_readiness.to_dict()
        result["support_parameters"] = {
            "performance_days": performance_days,
            "market_days": market_days,
            "trend_hours": trend_hours,
        }
        if window.start < window.snapshot_test_start:
            result["limitations"].append(
                "requested dates include train/validation data; results are in-sample"
            )
        if window.includes_post_test_period:
            result["limitations"].append(
                "requested dates extend beyond the frozen snapshot test end; "
                "these are post-test warehouse outcomes"
            )
        result["limitations"].append(
            "the policy may have been designed after model test results were inspected"
        )
        return result, observations
