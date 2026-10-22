"""Repair exact warehouse gaps with the smallest useful set of Binance archives."""
from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import hashlib
from pathlib import Path

from pipeline.batch.binance_archive_downloader import download_period
from pipeline.batch.staging_writer import StagingRepository
from pipeline.batch.warehouse_loader import run as load_warehouse
from pipeline.decision.config import last_closed_hour
from pipeline.decision.data.coverage import CoverageAuditor, CoverageReport
from pipeline.decision.data.warehouse_repository import HourlyCandleRepository
from pipeline.decision.types import TimeRange, utc_datetime
from pipeline.settings import BATCH, BINANCE_DATA_URL, DATABASE_URL, RAW_DIR


@dataclass(frozen=True, order=True)
class ArchiveRequest:
    """One monthly/daily archive needed to cover at least one DW gap."""

    symbol: str
    interval: str
    period: str
    fallback_days: tuple[str, ...] = ()


@dataclass(frozen=True)
class BackfillPlan:
    reports: tuple[CoverageReport, ...]
    archives: tuple[ArchiveRequest, ...]
    missing_hours: int
    deferred_hours: int


@dataclass(frozen=True)
class BackfillResult:
    extract_batch_id: int | None
    load_batch_id: int | None
    rows_staged: int
    rows_loaded: int
    archives: int
    archives_planned: int = 0
    archives_downloaded: int = 0
    archives_new: int = 0
    archives_changed: int = 0
    archives_repaired: int = 0
    archives_unavailable: int = 0
    missing_hours_before: int = 0
    missing_hours_after: int = 0
    deferred_hours: int = 0


def _missing_hours(report: CoverageReport) -> int:
    return sum(
        int((missing.end - missing.start) / timedelta(hours=1))
        for missing in report.missing_ranges
    )


def _range_days(missing: TimeRange) -> list[date]:
    """Return UTC dates containing one or more missing hourly candles."""
    if missing.start >= missing.end:
        return []
    current = utc_datetime(missing.start).date()
    final = (utc_datetime(missing.end) - timedelta(microseconds=1)).date()
    values = []
    while current <= final:
        values.append(current)
        current += timedelta(days=1)
    return values


def plan_missing_archives(
    reports: Sequence[CoverageReport], today: date
) -> tuple[tuple[ArchiveRequest, ...], int]:
    """Map exact DW gaps to monthly archives or completed current-month days.

    Old gaps use one monthly archive per affected month. For the immediately
    preceding month, ``fallback_days`` lets the downloader use only affected
    daily archives while Binance has not published the monthly archive yet.
    Current-day candles cannot be repaired from the public daily archive and
    are reported as deferred instead of causing pointless 404 requests.
    """
    monthly_days: dict[tuple[str, str], set[str]] = {}
    daily: set[tuple[str, str]] = set()
    deferred_hours = 0
    current_month = (today.year, today.month)

    for report in reports:
        symbol = report.symbol.upper()
        for missing in report.missing_ranges:
            for day in _range_days(missing):
                if day >= today:
                    day_start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
                    overlap_start = max(utc_datetime(missing.start), day_start)
                    overlap_end = min(
                        utc_datetime(missing.end), day_start + timedelta(days=1)
                    )
                    deferred_hours += max(
                        0, int((overlap_end - overlap_start) / timedelta(hours=1))
                    )
                elif (day.year, day.month) < current_month:
                    key = (symbol, day.strftime("%Y-%m"))
                    monthly_days.setdefault(key, set()).add(day.isoformat())
                else:
                    daily.add((symbol, day.isoformat()))

    requests = [
        ArchiveRequest(symbol, "1h", period, tuple(sorted(days)))
        for (symbol, period), days in monthly_days.items()
    ]
    requests.extend(
        ArchiveRequest(symbol, "1h", period)
        for symbol, period in daily
    )
    return tuple(sorted(requests)), deferred_hours


class BackfillService:
    def __init__(
        self,
        repository: HourlyCandleRepository | None = None,
        database_url: str = DATABASE_URL,
        raw_dir: Path | str = RAW_DIR,
        staging_repository: StagingRepository | None = None,
    ):
        self.repository = repository or HourlyCandleRepository(database_url)
        self.database_url = database_url
        self.raw_dir = Path(raw_dir)
        self.staging = staging_repository or StagingRepository(database_url)
        self.auditor = CoverageAuditor()

    def audit(
        self, symbols: Sequence[str], starts: dict[str, datetime], end: datetime
    ) -> list[CoverageReport]:
        end = utc_datetime(end)
        reports = []
        for raw_symbol in symbols:
            symbol = raw_symbol.upper()
            start = utc_datetime(starts[symbol])
            candles = self.repository.fetch_candles(symbol, start, end)
            reports.append(self.auditor.audit(candles, start, end, symbol))
        return reports

    def plan(
        self,
        symbols: Sequence[str],
        start_month: str,
        end: datetime | None = None,
        today: date | None = None,
    ) -> BackfillPlan:
        start = datetime.strptime(start_month, "%Y-%m").replace(tzinfo=UTC)
        end = utc_datetime(end or last_closed_hour())
        today = today or datetime.now(UTC).date()
        if start >= end:
            raise ValueError("backfill start month must be before end")
        normalized = tuple(dict.fromkeys(symbol.upper() for symbol in symbols))
        if not normalized:
            raise ValueError("backfill requires at least one symbol")
        reports = tuple(self.audit(normalized, dict.fromkeys(normalized, start), end))
        archives, deferred = plan_missing_archives(reports, today)
        return BackfillPlan(
            reports=reports,
            archives=archives,
            missing_hours=sum(_missing_hours(report) for report in reports),
            deferred_hours=deferred,
        )

    def _download(
        self, request: ArchiveRequest, today: date
    ) -> list[tuple[str, str, Path]]:
        paths = download_period(
            BINANCE_DATA_URL,
            self.raw_dir,
            request.symbol,
            request.interval,
            request.period,
            today,
            refresh=True,
            fallback_days=request.fallback_days or None,
        )
        return [(request.symbol, request.interval, path) for path in paths]

    def backfill(
        self,
        symbols: Sequence[str],
        start_month: str,
        workers: int | None = None,
        *,
        end: datetime | None = None,
        today: date | None = None,
    ) -> BackfillResult:
        """Audit, selectively stage gap archives, then UPSERT them into DW."""
        end = utc_datetime(end or last_closed_hour())
        today = today or datetime.now(UTC).date()
        plan = self.plan(symbols, start_month, end=end, today=today)
        if not plan.archives:
            return BackfillResult(
                None, None, 0, 0, 0,
                missing_hours_before=plan.missing_hours,
                missing_hours_after=plan.missing_hours,
                deferred_hours=plan.deferred_hours,
            )

        workers = workers if workers is not None else int(BATCH["workers"])
        downloaded: list[tuple[str, str, Path]] = []
        unavailable = 0
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for files in executor.map(
                lambda request: self._download(request, today), plan.archives
            ):
                if not files:
                    unavailable += 1
                downloaded.extend(files)

        # Monthly fallback and overlapping ranges can resolve to the same daily
        # archive. Stage every physical archive at most once in this batch.
        unique: dict[tuple[str, str, str], tuple[str, str, Path]] = {}
        for symbol, interval, path in downloaded:
            unique[(symbol, interval, path.name)] = (symbol, interval, path)
        files = list(unique.values())
        if not files:
            return BackfillResult(
                None, None, 0, 0, 0,
                archives_planned=len(plan.archives),
                archives_unavailable=unavailable,
                missing_hours_before=plan.missing_hours,
                missing_hours_after=plan.missing_hours,
                deferred_hours=plan.deferred_hours,
            )

        # A matching loaded checksum normally means idempotent data. These files
        # are still staged because the DW audit proved that at least one covered
        # candle is absent (for example, an earlier DQ rejection or manual loss).
        loaded = self.staging.loaded_checksums([path.name for _, _, path in files])
        archives_new = archives_changed = archives_repaired = 0
        for _, _, path in files:
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            previous = loaded.get(path.name)
            if previous is None:
                archives_new += 1
            elif previous != checksum:
                archives_changed += 1
            else:
                archives_repaired += 1

        extract_batch_id, rows_staged = self.staging.load(files, replace=False)
        loaded_summary = load_warehouse(
            self.database_url, extract_batch_id=extract_batch_id
        )

        start = datetime.strptime(start_month, "%Y-%m").replace(tzinfo=UTC)
        normalized = tuple(dict.fromkeys(symbol.upper() for symbol in symbols))
        after = self.audit(normalized, dict.fromkeys(normalized, start), end)
        return BackfillResult(
            extract_batch_id=int(extract_batch_id),
            load_batch_id=int(loaded_summary["batch_id"]),
            rows_staged=int(rows_staged),
            rows_loaded=int(loaded_summary["rows_loaded"]),
            archives=len(files),
            archives_planned=len(plan.archives),
            archives_downloaded=len(files),
            archives_new=archives_new,
            archives_changed=archives_changed,
            archives_repaired=archives_repaired,
            archives_unavailable=unavailable,
            missing_hours_before=plan.missing_hours,
            missing_hours_after=sum(_missing_hours(report) for report in after),
            deferred_hours=plan.deferred_hours,
        )

    def verify(
        self, symbols: Sequence[str], starts: dict[str, datetime], end: datetime
    ) -> list[CoverageReport]:
        reports = self.audit(symbols, starts, end)
        for report in reports:
            self.auditor.assert_trainable(report)
        return reports
