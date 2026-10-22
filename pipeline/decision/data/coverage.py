"""Audit candle coverage without fabricating missing periods."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

import pandas as pd

from pipeline.decision.types import TimeRange, utc_datetime


@dataclass(frozen=True)
class CoverageReport:
    symbol: str
    requested_start: datetime
    requested_end: datetime
    first_candle: datetime | None
    last_candle: datetime | None
    row_count: int
    duplicate_count: int
    missing_ranges: tuple[TimeRange, ...]

    @property
    def is_complete(self) -> bool:
        return self.row_count > 0 and self.duplicate_count == 0 and not self.missing_ranges

    def to_dict(self) -> dict:
        value = asdict(self)
        value["is_complete"] = self.is_complete
        return value


def _period_delta(frequency: str) -> pd.Timedelta:
    if frequency == "1h":
        return pd.Timedelta(hours=1)
    if frequency == "1d":
        return pd.Timedelta(days=1)
    raise ValueError(f"unsupported frequency: {frequency}")


def _group_missing(
    values: pd.DatetimeIndex, frequency: str = "1h"
) -> tuple[TimeRange, ...]:
    if values.empty:
        return ()
    step = _period_delta(frequency)
    groups: list[TimeRange] = []
    start = previous = values[0]
    for current in values[1:]:
        if current - previous != step:
            groups.append(TimeRange(start.to_pydatetime(), (previous + step).to_pydatetime()))
            start = current
        previous = current
    groups.append(TimeRange(start.to_pydatetime(), (previous + step).to_pydatetime()))
    return tuple(groups)


class CoverageAuditor:
    def __init__(self, frequency: str = "1h"):
        self.frequency = frequency
        self.step = _period_delta(frequency)

    def audit(
        self, candles: pd.DataFrame, start: datetime, end: datetime, symbol: str | None = None
    ) -> CoverageReport:
        start, end = utc_datetime(start), utc_datetime(end)
        if start >= end:
            raise ValueError("coverage start must be before end")
        if "open_time" not in candles:
            raise ValueError("candles must contain open_time")
        values = pd.to_datetime(candles["open_time"], utc=True)
        resolved_symbol = symbol
        if resolved_symbol is None and "symbol" in candles and not candles.empty:
            unique = candles["symbol"].dropna().astype(str).str.upper().unique()
            if len(unique) != 1:
                raise ValueError("coverage audit requires exactly one symbol")
            resolved_symbol = unique[0]
        resolved_symbol = (resolved_symbol or "UNKNOWN").upper()
        inside = values[(values >= pd.Timestamp(start)) & (values < pd.Timestamp(end))]
        duplicates = int(inside.duplicated().sum())
        actual = pd.DatetimeIndex(inside.drop_duplicates().sort_values())
        expected = pd.date_range(
            start, end, freq=self.frequency, inclusive="left", tz="UTC"
        )
        missing = expected.difference(actual)
        return CoverageReport(
            symbol=resolved_symbol,
            requested_start=start,
            requested_end=end,
            first_candle=None if actual.empty else actual[0].to_pydatetime(),
            last_candle=None if actual.empty else actual[-1].to_pydatetime(),
            row_count=len(inside),
            duplicate_count=duplicates,
            missing_ranges=_group_missing(missing, self.frequency),
        )

    def assert_trainable(self, report: CoverageReport) -> None:
        period_label = "hours" if self.frequency == "1h" else "days"
        candle_label = "hourly" if self.frequency == "1h" else "daily"
        if report.row_count == 0:
            raise ValueError(f"{report.symbol}: no {candle_label} candles in requested range")
        if report.duplicate_count:
            raise ValueError(
                f"{report.symbol}: {report.duplicate_count} duplicate {candle_label} candles"
            )
        if report.missing_ranges:
            missing_periods = sum(
                int((item.end - item.start) / self.step)
                for item in report.missing_ranges
            )
            raise ValueError(
                f"{report.symbol}: {missing_periods} missing {period_label} in "
                f"{len(report.missing_ranges)} ranges"
            )
