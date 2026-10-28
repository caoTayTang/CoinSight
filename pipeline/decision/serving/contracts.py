"""Contracts shared by readiness, inference and the public support tool."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from pipeline.decision.types import TimeRange, utc_datetime

PUBLIC_SYMBOLS = ("BTC", "ETH")


def range_dict(value: TimeRange) -> dict[str, str]:
    return {"start": value.start.isoformat(), "end": value.end.isoformat()}


@dataclass(frozen=True)
class ForecastSupportRequest:
    symbol: str = "BTC"
    performance_days: int = 30
    market_days: int = 30
    trend_hours: int = 168
    cutoff: datetime | None = None

    def __post_init__(self) -> None:
        symbol = str(self.symbol).upper()
        if symbol not in PUBLIC_SYMBOLS:
            raise ValueError(f"symbol must be one of {list(PUBLIC_SYMBOLS)}")
        for name, value, lower, upper in (
            ("performance_days", self.performance_days, 7, 365),
            ("market_days", self.market_days, 7, 365),
            ("trend_hours", self.trend_hours, 24, 1000),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or not lower <= value <= upper:
                raise ValueError(f"{name} must be an integer in [{lower}, {upper}]")
        object.__setattr__(self, "symbol", symbol)
        if self.cutoff is not None:
            object.__setattr__(self, "cutoff", utc_datetime(self.cutoff))


@dataclass(frozen=True)
class DataRequirements:
    symbol: str
    daily_cutoff: datetime
    hourly_cutoff: datetime
    required_daily_symbols: tuple[str, ...]
    daily_range: TimeRange
    hourly_range: TimeRange


@dataclass(frozen=True)
class DataReadinessReport:
    daily_cutoff: datetime
    hourly_cutoff: datetime
    required_daily_symbols: tuple[str, ...]
    daily_range: TimeRange
    hourly_range: TimeRange
    missing_daily_ranges: dict[str, tuple[TimeRange, ...]]
    missing_hourly_ranges: dict[str, tuple[TimeRange, ...]]
    duplicate_rows: int
    invalid_rows: int
    is_complete: bool
    backfill_performed: bool = False
    backfill_reason: str = "not_attempted"
    extract_batch_ids: tuple[int, ...] = ()
    load_batch_ids: tuple[int, ...] = ()
    sync_details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "daily_cutoff": self.daily_cutoff.isoformat(),
            "hourly_cutoff": self.hourly_cutoff.isoformat(),
            "required_daily_symbols": list(self.required_daily_symbols),
            "daily_range": range_dict(self.daily_range),
            "hourly_range": range_dict(self.hourly_range),
            "missing_daily_ranges": {
                symbol: [range_dict(item) for item in ranges]
                for symbol, ranges in self.missing_daily_ranges.items()
            },
            "missing_hourly_ranges": {
                symbol: [range_dict(item) for item in ranges]
                for symbol, ranges in self.missing_hourly_ranges.items()
            },
            "duplicate_rows": self.duplicate_rows,
            "invalid_rows": self.invalid_rows,
            "is_complete": self.is_complete,
            "backfill_performed": self.backfill_performed,
            "backfill_reason": self.backfill_reason,
            "extract_batch_ids": list(self.extract_batch_ids),
            "load_batch_ids": list(self.load_batch_ids),
            "sync_details": self.sync_details,
        }


@dataclass(frozen=True)
class SyncResult:
    extract_batch_ids: tuple[int, ...] = ()
    load_batch_ids: tuple[int, ...] = ()
    archives_planned: int = 0
    archives_loaded: int = 0
    rest_requests: int = 0
    rows_staged: int = 0
    rows_loaded: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
