"""Audit exact serving ranges before any optional warehouse mutation."""
from __future__ import annotations

from dataclasses import replace
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Protocol

import numpy as np
import pandas as pd

from pipeline.decision.data.coverage import CoverageAuditor
from pipeline.decision.data.feature_extractor import feature_warmup_periods
from pipeline.decision.data.warehouse_repository import (
    DailyCandleRepository,
    HourlyCandleRepository,
)
from pipeline.decision.serving.contracts import (
    DataReadinessReport,
    DataRequirements,
    ForecastSupportRequest,
    SyncResult,
)
from pipeline.decision.serving.model_bundle import ForecastModelBundle
from pipeline.decision.types import TimeRange, utc_datetime


class MissingDataSynchronizer(Protocol):
    def sync(self, readiness: DataReadinessReport) -> SyncResult: ...


def _valid_candles(frame: pd.DataFrame) -> np.ndarray:
    if frame.empty:
        return np.zeros(0, dtype=bool)
    numeric = frame[[
        "open_price", "high_price", "low_price", "close_price",
        "volume_quote", "trade_count",
    ]].apply(pd.to_numeric, errors="coerce")
    finite = np.isfinite(numeric).all(axis=1).to_numpy()
    positive = numeric[["open_price", "high_price", "low_price", "close_price"]].gt(0).all(axis=1)
    bounds = (
        numeric["high_price"].ge(numeric[["open_price", "low_price", "close_price"]].max(axis=1))
        & numeric["low_price"].le(numeric[["open_price", "close_price"]].min(axis=1))
    )
    non_negative = numeric["volume_quote"].ge(0) & numeric["trade_count"].ge(0)
    return finite & positive.to_numpy() & bounds.to_numpy() & non_negative.to_numpy()


class ForecastDataReadinessService:
    def __init__(
        self,
        daily_repository: DailyCandleRepository | None = None,
        hourly_repository: HourlyCandleRepository | None = None,
        synchronizer: MissingDataSynchronizer | None = None,
        *,
        now_fn=None,
    ):
        self.daily = daily_repository or DailyCandleRepository()
        self.hourly = hourly_repository or HourlyCandleRepository()
        self.synchronizer = synchronizer
        self.now_fn = now_fn or (lambda: datetime.now(UTC))
        self._lock = Lock()

    def required_ranges(
        self, bundle: ForecastModelBundle, request: ForecastSupportRequest
    ) -> DataRequirements:
        now = utc_datetime(self.now_fn())
        observed = utc_datetime(request.cutoff or now)
        if observed > now:
            raise ValueError("cutoff cannot be in the future")
        daily_cutoff = pd.Timestamp(observed).floor("D").to_pydatetime()
        hourly_cutoff = pd.Timestamp(observed).floor("h").to_pydatetime()
        warmup = feature_warmup_periods(bundle.feature_version)
        realized = max(request.performance_days, request.market_days)
        daily_periods = (
            warmup + bundle.lookback_periods
            + realized + int(bundle.manifest["horizon_periods"])
        )
        return DataRequirements(
            symbol=bundle.symbol,
            daily_cutoff=daily_cutoff,
            hourly_cutoff=hourly_cutoff,
            required_daily_symbols=bundle.required_symbols(),
            daily_range=TimeRange(
                daily_cutoff - timedelta(days=daily_periods), daily_cutoff
            ),
            hourly_range=TimeRange(
                hourly_cutoff - timedelta(hours=request.trend_hours + 1),
                hourly_cutoff,
            ),
        )

    @staticmethod
    def _audit_one(repository, auditor, symbol: str, required: TimeRange):
        frame = repository.fetch_candles(symbol, required.start, required.end)
        duplicate_count = 0 if frame.empty else int(
            pd.to_datetime(frame["open_time"], utc=True).duplicated().sum()
        )
        valid = _valid_candles(frame)
        invalid_count = int((~valid).sum())
        coverage_frame = frame.loc[valid].copy() if len(valid) else frame.copy()
        coverage = auditor.audit(
            coverage_frame, required.start, required.end, symbol
        )
        return frame, coverage, duplicate_count, invalid_count

    def audit(self, requirements: DataRequirements) -> DataReadinessReport:
        daily_missing = {}
        hourly_missing = {}
        duplicates = invalid = 0
        daily_auditor = CoverageAuditor("1d")
        hourly_auditor = CoverageAuditor("1h")
        for symbol in requirements.required_daily_symbols:
            _, coverage, duplicate_count, invalid_count = self._audit_one(
                self.daily, daily_auditor, symbol, requirements.daily_range
            )
            daily_missing[symbol] = coverage.missing_ranges
            duplicates += duplicate_count
            invalid += invalid_count
        _, coverage, duplicate_count, invalid_count = self._audit_one(
            self.hourly, hourly_auditor, requirements.symbol, requirements.hourly_range
        )
        hourly_missing[requirements.symbol] = coverage.missing_ranges
        duplicates += duplicate_count
        invalid += invalid_count
        complete = (
            duplicates == 0
            and invalid == 0
            and not any(daily_missing.values())
            and not any(hourly_missing.values())
        )
        return DataReadinessReport(
            daily_cutoff=requirements.daily_cutoff,
            hourly_cutoff=requirements.hourly_cutoff,
            required_daily_symbols=requirements.required_daily_symbols,
            daily_range=requirements.daily_range,
            hourly_range=requirements.hourly_range,
            missing_daily_ranges=daily_missing,
            missing_hourly_ranges=hourly_missing,
            duplicate_rows=duplicates,
            invalid_rows=invalid,
            is_complete=complete,
            backfill_reason=(
                "warehouse_already_complete" if complete else "warehouse_incomplete"
            ),
        )

    def ensure_ready(
        self, bundle: ForecastModelBundle, request: ForecastSupportRequest
    ) -> tuple[DataRequirements, DataReadinessReport]:
        requirements = self.required_ranges(bundle, request)
        return requirements, self.ensure_requirements(requirements)

    def ensure_requirements(self, requirements: DataRequirements) -> DataReadinessReport:
        """Audit and optionally repair an already-computed bounded grid.

        Historical replay uses this entry point for the union of all per-day
        model windows, so repair happens once before rows are prefetched.
        """
        with self._lock:
            before = self.audit(requirements)
            if before.is_complete:
                return replace(
                    before,
                    backfill_performed=False,
                    backfill_reason="warehouse_already_complete",
                )
            if self.synchronizer is None:
                return replace(
                    before,
                    backfill_performed=False,
                    backfill_reason="synchronizer_unavailable",
                )
            lock_factory = getattr(self.synchronizer, "lock", None)
            lock = lock_factory(before) if lock_factory is not None else nullcontext()
            with lock:
                # Another process may have completed the same repair while this
                # request waited for the distributed lock. Audit again first.
                locked = self.audit(requirements)
                if locked.is_complete:
                    return replace(
                        locked,
                        backfill_performed=False,
                        backfill_reason="warehouse_completed_by_concurrent_request",
                    )
                sync = self.synchronizer.sync(locked)
            after = self.audit(requirements)
            return replace(
                after,
                backfill_performed=bool(
                    sync.archives_loaded or sync.rest_requests or sync.rows_staged
                ),
                backfill_reason=(
                    "missing_ranges_synced"
                    if after.is_complete else "missing_ranges_remain_after_sync"
                ),
                extract_batch_ids=sync.extract_batch_ids,
                load_batch_ids=sync.load_batch_ids,
                sync_details=sync.to_dict(),
            )
