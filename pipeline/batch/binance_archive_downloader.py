"""Download and verify Binance public data ZIP archives."""
from __future__ import annotations

from datetime import date, timedelta
import hashlib
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pipeline.batch.binance_archive_format import QUOTE_ASSET, kline_url, month_days
from pipeline.settings import BATCH

SOURCE_CODE = "binance"

def fetch(url: str, timeout: float | None = None, attempts: int | None = None) -> bytes | None:
    """Return the body, or None for 404. Network errors and 5xx are retried."""
    timeout = timeout if timeout is not None else BATCH["archive_timeout_seconds"]
    attempts = attempts if attempts is not None else BATCH["archive_attempts"]
    request = Request(url, headers={"User-Agent": "CoinSight/1.0"})
    for attempt in range(1, attempts + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except HTTPError as error:
            if error.code == 404:
                return None
            if error.code < 500 or attempt == attempts:
                raise
        except (URLError, TimeoutError):
            if attempt == attempts:
                raise
        time.sleep(2 * attempt)
    raise AssertionError("unreachable")


def verify_checksum(path: Path, checksum_text: str) -> None:
    expected = checksum_text.split()[0].lower()
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(f"checksum mismatch for {path.name}")


def download_archive(url: str, destination: Path, *, refresh: bool = False) -> Path | None:
    """Return a checksum-verified archive; refresh detects publisher revisions."""
    if destination.exists() and not refresh:
        return destination

    checksum = fetch(f"{url}.CHECKSUM")
    if checksum is None:
        if destination.exists():
            raise ValueError(f"missing checksum for cached archive {url}")
        return None
    if destination.exists():
        try:
            verify_checksum(destination, checksum.decode())
            return destination
        except ValueError:
            pass

    content = fetch(url)
    if content is None:
        return None

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    partial.write_bytes(content)
    try:
        verify_checksum(partial, checksum.decode())
    except ValueError:
        partial.unlink()
        raise
    partial.rename(destination)
    return destination


def download_period(
    base_url: str, raw_dir: Path, symbol: str, interval: str, period: str, today: date
) -> list[Path]:
    pair = f"{symbol.upper()}{QUOTE_ASSET}"
    url = kline_url(base_url, symbol, interval, period)
    path = download_archive(url, raw_dir / SOURCE_CODE / pair / interval / url.rsplit("/", 1)[1])
    if path is not None:
        return [path]

    # Binance publishes last month's archive a few days into the new month.
    year, month = (int(part) for part in period.split("-")[:2])
    last_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    if len(period) == 7 and period == last_month:
        return [
            path
            for day in month_days(year, month, today)
            for path in download_period(base_url, raw_dir, symbol, interval, day, today)
        ]
    return []
