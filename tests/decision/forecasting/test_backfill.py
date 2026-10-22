from datetime import UTC, date, datetime
import hashlib

from pipeline.decision.data import backfill as backfill_module
from pipeline.decision.data.backfill import (
    ArchiveRequest,
    BackfillPlan,
    BackfillService,
    plan_missing_archives,
)
from pipeline.decision.data.coverage import CoverageReport
from pipeline.decision.types import TimeRange


class NoopRepository:
    pass


class FakeStagingRepository:
    def __init__(self, checksums):
        self.checksums = checksums
        self.loaded = []

    def loaded_checksums(self, filenames):
        assert set(filenames) == set(self.checksums)
        return self.checksums

    def load(self, files, *, replace=True):
        self.loaded.append((files, replace))
        return 11, 100


def report(*ranges):
    return CoverageReport(
        symbol="BTC",
        requested_start=datetime(2026, 8, 1, tzinfo=UTC),
        requested_end=datetime(2026, 9, 4, 6, tzinfo=UTC),
        first_candle=None,
        last_candle=None,
        row_count=1,
        duplicate_count=0,
        missing_ranges=tuple(TimeRange(*value) for value in ranges),
    )


def test_missing_ranges_map_to_minimal_monthly_and_daily_archives():
    missing = report(
        (
            datetime(2026, 8, 2, 3, tzinfo=UTC),
            datetime(2026, 8, 2, 5, tzinfo=UTC),
        ),
        (
            datetime(2026, 8, 20, 9, tzinfo=UTC),
            datetime(2026, 8, 20, 10, tzinfo=UTC),
        ),
        (
            datetime(2026, 9, 3, 10, tzinfo=UTC),
            datetime(2026, 9, 4, 2, tzinfo=UTC),
        ),
    )

    archives, deferred = plan_missing_archives([missing], date(2026, 9, 4))

    assert archives == (
        ArchiveRequest(
            "BTC", "1h", "2026-08", ("2026-08-02", "2026-08-20")
        ),
        ArchiveRequest("BTC", "1h", "2026-09-03"),
    )
    assert deferred == 2


def test_backfill_stages_only_planned_gap_archives_and_upserts(monkeypatch, tmp_path):
    first = tmp_path / "BTCUSDT-1h-2026-08.zip"
    second = tmp_path / "BTCUSDT-1h-2026-09-03.zip"
    first.write_bytes(b"same")
    second.write_bytes(b"revised")
    staging = FakeStagingRepository(
        {
            first.name: hashlib.sha256(first.read_bytes()).hexdigest(),
            second.name: "old-checksum",
        }
    )
    service = BackfillService(
        NoopRepository(), "postgresql://test", tmp_path, staging_repository=staging
    )
    before = report(
        (
            datetime(2026, 8, 2, 3, tzinfo=UTC),
            datetime(2026, 8, 2, 4, tzinfo=UTC),
        )
    )
    plan = BackfillPlan(
        reports=(before,),
        archives=(
            ArchiveRequest("BTC", "1h", "2026-08"),
            ArchiveRequest("BTC", "1h", "2026-09-03"),
        ),
        missing_hours=1,
        deferred_hours=0,
    )
    monkeypatch.setattr(service, "plan", lambda *args, **kwargs: plan)
    monkeypatch.setattr(
        service,
        "_download",
        lambda request, today: [
            ("BTC", "1h", first if request.period == "2026-08" else second)
        ],
    )
    complete = report()
    monkeypatch.setattr(service, "audit", lambda *args, **kwargs: [complete])

    def fake_load(database_url, extract_batch_id):
        assert database_url == "postgresql://test"
        assert extract_batch_id == 11
        return {"batch_id": 12, "rows_loaded": 1}

    monkeypatch.setattr(backfill_module, "load_warehouse", fake_load)

    result = service.backfill(
        ["BTC"], "2026-08", workers=2,
        end=datetime(2026, 9, 4, tzinfo=UTC), today=date(2026, 9, 4)
    )

    assert result.extract_batch_id == 11
    assert result.load_batch_id == 12
    assert result.archives == 2
    assert result.archives_repaired == 1
    assert result.archives_changed == 1
    assert result.missing_hours_before == 1
    assert result.missing_hours_after == 0
    assert staging.loaded[0][1] is False


def test_backfill_is_noop_when_dw_is_complete(monkeypatch, tmp_path):
    service = BackfillService(
        NoopRepository(), "postgresql://test", tmp_path,
        staging_repository=FakeStagingRepository({}),
    )
    complete = report()
    monkeypatch.setattr(
        service,
        "plan",
        lambda *args, **kwargs: BackfillPlan((complete,), (), 0, 0),
    )

    result = service.backfill(
        ["BTC"], "2026-08", end=datetime(2026, 9, 1, tzinfo=UTC),
        today=date(2026, 9, 4)
    )

    assert result.extract_batch_id is None
    assert result.load_batch_id is None
    assert result.archives == 0
    assert result.missing_hours_after == 0
