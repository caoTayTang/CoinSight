from __future__ import annotations

from datetime import UTC, datetime
import json

import numpy as np
import pandas as pd
import pytest

from pipeline.decision.artifacts.store import file_sha256
from pipeline.decision.serving.contracts import (
    DataReadinessReport, ForecastSupportRequest, SyncResult,
)
from pipeline.decision.serving.data_readiness import ForecastDataReadinessService
from pipeline.decision.serving.market_statistics import MarketStatisticsService
from pipeline.decision.serving.model_bundle import BUNDLE_FILES, ForecastModelBundle
from pipeline.decision.serving.support_service import ForecastSupportService
from pipeline.decision.serving.targeted_sync import TargetedBackfillService
from pipeline.decision.types import TimeRange


class FakeBundle:
    symbol = "BTC"
    feature_version = "daily-return-v2"
    lookback_periods = 90
    manifest = {"horizon_periods": 1}

    @staticmethod
    def required_symbols():
        return ("BTC", "ETH")


def candles(symbol: str, start, end, frequency: str) -> pd.DataFrame:
    times = pd.date_range(start, end, freq=frequency, inclusive="left", tz="UTC")
    values = np.arange(len(times), dtype=float) + 100.0
    return pd.DataFrame({
        "symbol": symbol,
        "open_time": times,
        "open_price": values,
        "high_price": values + 2,
        "low_price": values - 2,
        "close_price": values + 1,
        "volume_quote": np.full(len(times), 1000.0),
        "trade_count": np.full(len(times), 10),
        "batch_id": np.full(len(times), 1),
    })


class FrameRepository:
    def __init__(self, frequency):
        self.frequency = frequency
        self.frames = {}

    def fetch_candles(self, symbol, start, end):
        frame = self.frames.get(symbol, candles(symbol, start, start, self.frequency))
        times = pd.to_datetime(frame["open_time"], utc=True)
        return frame.loc[
            (times >= pd.Timestamp(start)) & (times < pd.Timestamp(end))
        ].reset_index(drop=True)


class CompletingSynchronizer:
    def __init__(self, daily, hourly):
        self.daily = daily
        self.hourly = hourly
        self.calls = 0

    def sync(self, readiness):
        self.calls += 1
        for symbol in readiness.required_daily_symbols:
            self.daily.frames[symbol] = candles(
                symbol, readiness.daily_range.start, readiness.daily_range.end, "1D"
            )
        self.hourly.frames["BTC"] = candles(
            "BTC", readiness.hourly_range.start, readiness.hourly_range.end, "1h"
        )
        return SyncResult(
            extract_batch_ids=(11,), load_batch_ids=(12,), rest_requests=1,
            rows_staged=3, rows_loaded=3,
        )


def readiness_fixture():
    daily, hourly = FrameRepository("1D"), FrameRepository("1h")
    sync = CompletingSynchronizer(daily, hourly)
    service = ForecastDataReadinessService(
        daily, hourly, sync,
        now_fn=lambda: datetime(2026, 10, 23, 12, 30, tzinfo=UTC),
    )
    request = ForecastSupportRequest(
        symbol="BTC", performance_days=30, market_days=30, trend_hours=168
    )
    requirements = service.required_ranges(FakeBundle(), request)
    return service, sync, request, requirements, daily, hourly


def test_request_contract_normalizes_symbol_and_rejects_unbounded_input():
    assert ForecastSupportRequest(symbol="eth").symbol == "ETH"
    for kwargs in (
        {"symbol": "SOL"}, {"performance_days": 6}, {"market_days": 366},
        {"trend_hours": 23}, {"performance_days": True},
    ):
        with pytest.raises(ValueError):
            ForecastSupportRequest(**kwargs)


def test_complete_readiness_never_calls_synchronizer():
    service, sync, request, requirements, daily, hourly = readiness_fixture()
    for symbol in requirements.required_daily_symbols:
        daily.frames[symbol] = candles(
            symbol, requirements.daily_range.start, requirements.daily_range.end, "1D"
        )
    hourly.frames["BTC"] = candles(
        "BTC", requirements.hourly_range.start, requirements.hourly_range.end, "1h"
    )
    _, report = service.ensure_ready(FakeBundle(), request)
    assert report.is_complete
    assert not report.backfill_performed
    assert report.backfill_reason == "warehouse_already_complete"
    assert sync.calls == 0


def test_missing_context_or_hour_is_repaired_then_reaudited():
    service, sync, request, _, _, _ = readiness_fixture()
    _, report = service.ensure_ready(FakeBundle(), request)
    assert sync.calls == 1 and report.is_complete and report.backfill_performed
    assert report.extract_batch_ids == (11,) and report.load_batch_ids == (12,)
    assert report.backfill_reason == "missing_ranges_synced"


def test_invalid_candle_counts_as_missing_and_blocks_completion():
    service, _, request, requirements, daily, hourly = readiness_fixture()
    for symbol in requirements.required_daily_symbols:
        daily.frames[symbol] = candles(
            symbol, requirements.daily_range.start, requirements.daily_range.end, "1D"
        )
    daily.frames["ETH"].loc[0, "close_price"] = np.nan
    hourly.frames["BTC"] = candles(
        "BTC", requirements.hourly_range.start, requirements.hourly_range.end, "1h"
    )
    report = service.audit(requirements)
    assert not report.is_complete and report.invalid_rows == 1
    assert report.missing_daily_ranges["ETH"]


def test_market_aggregates_and_hourly_regression_are_finite():
    stats = MarketStatisticsService()
    daily = candles("BTC", "2026-01-01", "2026-02-02", "1D")
    hourly = candles("BTC", "2026-01-01", "2026-01-10", "1h")
    market = stats.daily_statistics(daily, 30)
    trend = stats.hourly_trend(hourly, 168)
    assert market["sample_count"] == 30 and market["up_days"] == 30
    assert trend["sample_count"] == 168 and trend["direction"] == "up"
    assert trend["regression_r_squared"] > 0.8
    assert all(np.isfinite(v) for v in (
        market["annualized_volatility"], trend["slope_per_hour"],
        trend["close_vs_ema_168h"],
    ))


def test_bundle_checksum_verification_happens_without_loading_model(tmp_path):
    for name in BUNDLE_FILES:
        (tmp_path / name).write_bytes(name.encode())
    checksums = {name: file_sha256(tmp_path / name) for name in BUNDLE_FILES}
    (tmp_path / "artifact_checksums.json").write_text(json.dumps(checksums))
    ForecastModelBundle._verify_directory(tmp_path)
    (tmp_path / "model.pt").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="model.pt"):
        ForecastModelBundle._verify_directory(tmp_path)


def test_targeted_sync_uses_archive_for_old_gap_and_rest_for_today():
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    old = TimeRange(
        datetime(2020, 1, 3, tzinfo=UTC), datetime(2020, 1, 4, tzinfo=UTC)
    )
    recent = TimeRange(now, now.replace(hour=now.hour) + pd.Timedelta(hours=1))
    report = DataReadinessReport(
        daily_cutoff=now, hourly_cutoff=now,
        required_daily_symbols=("BTC",),
        daily_range=old, hourly_range=recent,
        missing_daily_ranges={"BTC": (old,)},
        missing_hourly_ranges={"BTC": (recent,)},
        duplicate_rows=0, invalid_rows=0, is_complete=False,
    )
    service = TargetedBackfillService.__new__(TargetedBackfillService)
    service.max_archives = 10
    archives, rest, _ = service._requests(report)
    assert ("BTC", "1d", "2020-01") in archives
    assert rest == [("BTC", "1h", recent)]


def test_support_service_does_not_fallback_when_symbol_has_no_bundle(tmp_path):
    service = ForecastSupportService(bundle_root=tmp_path)
    result = service.report(symbol="ETH")
    assert result == {
        "status": "unavailable",
        "observed_at": result["observed_at"],
        "symbol": "ETH",
        "reason": "no_pinned_model_bundle",
    }
