from datetime import date, datetime, timezone
import hashlib
import zipfile

import pytest

from pipeline.batch.binance_archive_format import (
    kline_url,
    parse_kline_csv,
    plan_periods,
    read_zip_csv,
)
from pipeline.batch.binance_archive_downloader import verify_checksum


MS_ROW = (
    "1551398400000,135.32,136.26,135.32,135.82,8225.15,1551401999999,"
    "1116772.63,3877,3983.64,541093.98,0"
)
US_ROW = (
    "1785542400000000,1862.60,1867.64,1862.38,1864.70,4320.59,1785545999999999,"
    "8059269.74,40804,1900.93,3546490.61,0"
)


def test_kline_url_monthly_and_daily():
    base = "https://data.binance.vision/"
    assert kline_url(base, "btc", "1h", "2026-08") == (
        "https://data.binance.vision/data/spot/monthly/klines/"
        "BTCUSDT/1h/BTCUSDT-1h-2026-08.zip"
    )
    assert kline_url(base, "BTC", "1d", "2026-09-27") == (
        "https://data.binance.vision/data/spot/daily/klines/"
        "BTCUSDT/1d/BTCUSDT-1d-2026-09-27.zip"
    )


def test_plan_periods_uses_daily_files_for_current_month():
    periods = plan_periods("2026-07", today=date(2026, 9, 4))
    assert periods == ["2026-07", "2026-08", "2026-09-01", "2026-09-02", "2026-09-03"]


def test_plan_periods_on_first_day_of_month_has_no_daily_files():
    assert plan_periods("2026-08", today=date(2026, 9, 1)) == ["2026-08"]


def test_parse_handles_millisecond_and_microsecond_timestamps():
    rows = parse_kline_csv(f"{MS_ROW}\n{US_ROW}\n")

    assert rows[0]["open_time"] == datetime(2019, 3, 1, tzinfo=timezone.utc)
    assert rows[1]["open_time"] == datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert rows[0] == {
        "open_time": datetime(2019, 3, 1, tzinfo=timezone.utc),
        "open_price": "135.32",
        "high_price": "136.26",
        "low_price": "135.32",
        "close_price": "135.82",
        "volume_base": "8225.15",
        "volume_quote": "1116772.63",
        "trade_count": "3877",
    }


def test_parse_skips_header_row():
    header = (
        "open_time,open,high,low,close,volume,close_time,quote_volume,"
        "count,taker_buy_volume,taker_buy_quote_volume,ignore"
    )
    assert len(parse_kline_csv(f"{header}\n{MS_ROW}\n")) == 1


def test_parse_rejects_short_rows():
    with pytest.raises(ValueError, match="fewer than 9 fields"):
        parse_kline_csv("1551398400000,1,2,3\n")


def test_read_zip_csv_and_checksum(tmp_path):
    path = tmp_path / "BTCUSDT-1d-2019-03.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("BTCUSDT-1d-2019-03.csv", MS_ROW + "\n")

    assert read_zip_csv(path) == MS_ROW + "\n"

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    verify_checksum(path, f"{digest}  {path.name}\n")
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify_checksum(path, f"{'0' * 64}  {path.name}\n")


def test_read_zip_csv_requires_one_csv(tmp_path):
    path = tmp_path / "empty.zip"
    with zipfile.ZipFile(path, "w"):
        pass
    with pytest.raises(ValueError, match="expected one CSV"):
        read_zip_csv(path)



class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self.body


def fake_urlopen(outcomes: list):
    calls = []

    def urlopen(request, timeout):
        calls.append(request.full_url)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)

    return urlopen, calls


def test_fetch_retries_transient_network_errors(monkeypatch):
    from urllib.error import URLError

    from pipeline.batch import binance_archive_downloader as binance_downloader

    urlopen, calls = fake_urlopen(
        [URLError("name resolution failed"), TimeoutError("handshake"), b"archive"]
    )
    monkeypatch.setattr(binance_downloader, "urlopen", urlopen)
    monkeypatch.setattr(binance_downloader.time, "sleep", lambda seconds: None)

    assert binance_downloader.fetch("https://example.test/a.zip") == b"archive"
    assert len(calls) == 3


def test_fetch_gives_up_after_last_attempt(monkeypatch):
    from urllib.error import URLError

    from pipeline.batch import binance_archive_downloader as binance_downloader

    urlopen, calls = fake_urlopen([URLError("down")] * 3)
    monkeypatch.setattr(binance_downloader, "urlopen", urlopen)
    monkeypatch.setattr(binance_downloader.time, "sleep", lambda seconds: None)

    with pytest.raises(URLError):
        binance_downloader.fetch("https://example.test/a.zip")
    assert len(calls) == 3


def test_fetch_returns_none_for_missing_archive_without_retry(monkeypatch):
    from urllib.error import HTTPError

    from pipeline.batch import binance_archive_downloader as binance_downloader

    missing = HTTPError("https://example.test/a.zip", 404, "Not Found", {}, None)
    urlopen, calls = fake_urlopen([missing])
    monkeypatch.setattr(binance_downloader, "urlopen", urlopen)

    assert binance_downloader.fetch("https://example.test/a.zip") is None
    assert len(calls) == 1
