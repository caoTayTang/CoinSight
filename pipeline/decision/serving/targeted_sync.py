"""Targeted archive/REST repair for serving readiness gaps."""
from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pipeline.batch.binance_archive_downloader import download_period
from pipeline.batch.staging_writer import StagingRepository
from pipeline.batch.warehouse_loader import run as load_warehouse
from pipeline.decision.serving.contracts import DataReadinessReport, SyncResult
from pipeline.decision.types import TimeRange, utc_datetime
from pipeline.settings import BINANCE_DATA_URL, DATABASE_URL, RAW_DIR


class BinanceRestKlineClient:
    def __init__(
        self,
        base_url: str = "https://data-api.binance.vision",
        timeout: float = 20,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def fetch(
        self, symbol: str, interval: str, start: datetime, end: datetime
    ) -> list[dict]:
        start, end = utc_datetime(start), utc_datetime(end)
        step = timedelta(hours=1) if interval == "1h" else timedelta(days=1)
        cursor = start
        rows: list[dict] = []
        while cursor < end:
            query = urlencode({
                "symbol": f"{symbol.upper()}USDT",
                "interval": interval,
                "startTime": int(cursor.timestamp() * 1000),
                "endTime": int(end.timestamp() * 1000) - 1,
                "limit": 1000,
            })
            request = Request(
                f"{self.base_url}/api/v3/klines?{query}",
                headers={"User-Agent": "CoinSight/1.0"},
            )
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read())
            if not isinstance(payload, list) or not payload:
                break
            for item in payload:
                opened = datetime.fromtimestamp(int(item[0]) / 1000, UTC)
                if not start <= opened < end:
                    continue
                rows.append({
                    "open_time": opened,
                    "open_price": item[1],
                    "high_price": item[2],
                    "low_price": item[3],
                    "close_price": item[4],
                    "volume_base": item[5],
                    "volume_quote": item[7],
                    "trade_count": item[8],
                })
            next_cursor = datetime.fromtimestamp(int(payload[-1][0]) / 1000, UTC) + step
            if next_cursor <= cursor:
                raise ValueError("Binance REST pagination did not advance")
            cursor = next_cursor
            if len(payload) < 1000:
                break
        unique = {row["open_time"]: row for row in rows}
        return [unique[key] for key in sorted(unique)]


def _dates(value: TimeRange) -> list[date]:
    current = utc_datetime(value.start).date()
    final = (utc_datetime(value.end) - timedelta(microseconds=1)).date()
    result = []
    while current <= final:
        result.append(current)
        current += timedelta(days=1)
    return result


class TargetedBackfillService:
    def __init__(
        self,
        database_url: str = DATABASE_URL,
        raw_dir: Path | str = RAW_DIR,
        staging: StagingRepository | None = None,
        rest: BinanceRestKlineClient | None = None,
        max_archives: int = 256,
    ):
        self.database_url = database_url
        self.raw_dir = Path(raw_dir)
        self.staging = staging or StagingRepository(database_url)
        self.rest = rest or BinanceRestKlineClient()
        self.max_archives = max_archives

    @contextmanager
    def lock(self, readiness: DataReadinessReport):
        """Serialize the same bounded repair across service processes."""
        import psycopg2

        identity = "|".join((
            "forecast-support",
            ",".join(readiness.required_daily_symbols),
            readiness.daily_cutoff.isoformat(),
            readiness.hourly_cutoff.isoformat(),
        ))
        key = int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], "big")
        if key >= 2 ** 63:
            key -= 2 ** 64
        connection = psycopg2.connect(self.database_url, connect_timeout=5)
        try:
            with connection.cursor() as cursor:
                cursor.execute("set lock_timeout = '30s'")
                cursor.execute("select pg_advisory_lock(%s)", (key,))
            try:
                yield
            finally:
                with connection.cursor() as cursor:
                    cursor.execute("select pg_advisory_unlock(%s)", (key,))
        finally:
            connection.close()

    def _requests(self, readiness: DataReadinessReport):
        today = datetime.now(UTC).date()
        current_month = today.replace(day=1)
        archives: dict[tuple[str, str, str], list[TimeRange]] = defaultdict(list)
        rest: list[tuple[str, str, TimeRange]] = []
        mappings = (
            ("1d", readiness.missing_daily_ranges),
            ("1h", readiness.missing_hourly_ranges),
        )
        for interval, missing_by_symbol in mappings:
            for symbol, ranges in missing_by_symbol.items():
                for missing in ranges:
                    for day in _dates(missing):
                        day_start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
                        part = TimeRange(
                            max(utc_datetime(missing.start), day_start),
                            min(utc_datetime(missing.end), day_start + timedelta(days=1)),
                        )
                        if day >= today:
                            rest.append((symbol, interval, part))
                        else:
                            period = (
                                day.strftime("%Y-%m")
                                if day < current_month else day.isoformat()
                            )
                            archives[(symbol, interval, period)].append(part)
        if len(archives) > self.max_archives:
            raise ValueError(
                f"targeted sync requires {len(archives)} archives; limit is {self.max_archives}"
            )
        return archives, rest, today

    def sync(self, readiness: DataReadinessReport) -> SyncResult:
        if readiness.is_complete:
            return SyncResult()
        archives, rest_ranges, today = self._requests(readiness)
        archive_files = []
        for (symbol, interval, period), covered_ranges in sorted(archives.items()):
            paths = download_period(
                BINANCE_DATA_URL,
                self.raw_dir,
                symbol,
                interval,
                period,
                today,
                refresh=True,
                fallback_days=(
                    tuple(day.isoformat() for item in covered_ranges for day in _dates(item))
                    if len(period) == 7 else None
                ),
            )
            if paths:
                archive_files.extend((symbol, interval, path) for path in paths)
            else:
                rest_ranges.extend((symbol, interval, item) for item in covered_ranges)
        unique_files = {
            (symbol, interval, path.name): (symbol, interval, path)
            for symbol, interval, path in archive_files
        }
        extract_ids: list[int] = []
        load_ids: list[int] = []
        rows_staged = rows_loaded = 0
        if unique_files:
            extract_id, count = self.staging.load(list(unique_files.values()), replace=False)
            loaded = load_warehouse(self.database_url, extract_batch_id=extract_id)
            extract_ids.append(int(extract_id))
            load_ids.append(int(loaded["batch_id"]))
            rows_staged += int(count)
            rows_loaded += int(loaded["rows_loaded"])
        rest_requests = 0
        for symbol, interval, missing in rest_ranges:
            records = self.rest.fetch(symbol, interval, missing.start, missing.end)
            if not records:
                continue
            identity = hashlib.sha256(
                f"{symbol}|{interval}|{missing.start.isoformat()}|{missing.end.isoformat()}".encode()
            ).hexdigest()[:16]
            source_file = f"binance-rest-{symbol}-{interval}-{identity}.json"
            source_url = f"{self.rest.base_url}/api/v3/klines"
            extract_id, count = self.staging.load_records(
                symbol,
                interval,
                records,
                source_file=source_file,
                source_url=source_url,
            )
            loaded = load_warehouse(self.database_url, extract_batch_id=extract_id)
            extract_ids.append(int(extract_id))
            load_ids.append(int(loaded["batch_id"]))
            rows_staged += int(count)
            rows_loaded += int(loaded["rows_loaded"])
            rest_requests += 1
        return SyncResult(
            extract_batch_ids=tuple(extract_ids),
            load_batch_ids=tuple(load_ids),
            archives_planned=len(archives),
            archives_loaded=len(unique_files),
            rest_requests=rest_requests,
            rows_staged=rows_staged,
            rows_loaded=rows_loaded,
        )
