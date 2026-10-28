import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.decision.trading.historical_backtest import resolve_backtest_window


def bundle(snapshot_id="snapshot-1"):
    return SimpleNamespace(
        symbol="BTC",
        manifest={"snapshot_id": snapshot_id},
    )


def write_snapshot(root: Path):
    directory = root / "snapshot-1" / "BTC"
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text(json.dumps({
        "split_boundaries": {
            "validation_start": "2025-01-01T00:00:00+00:00",
            "test_start": "2026-01-01T00:00:00+00:00",
            "test_end": "2026-04-01T00:00:00+00:00",
        }
    }), encoding="utf-8")


def test_window_defaults_to_snapshot_test_split(tmp_path):
    write_snapshot(tmp_path)
    window = resolve_backtest_window(bundle(), tmp_path)
    assert window.start.isoformat() == "2026-01-01T00:00:00+00:00"
    assert window.end.isoformat() == "2026-04-01T00:00:00+00:00"
    assert window.uses_only_snapshot_test_split is True


def test_window_rejects_in_sample_dates_without_explicit_override(tmp_path):
    write_snapshot(tmp_path)
    with pytest.raises(ValueError, match="outside the frozen snapshot test split"):
        resolve_backtest_window(
            bundle(), tmp_path,
            start="2025-12-01", end="2026-02-01",
        )
    window = resolve_backtest_window(
        bundle(), tmp_path,
        start="2025-12-01", end="2026-02-01",
        allow_outside_test=True,
    )
    assert window.uses_only_snapshot_test_split is False


def test_window_requires_utc_day_boundaries(tmp_path):
    write_snapshot(tmp_path)
    with pytest.raises(ValueError, match="UTC day boundary"):
        resolve_backtest_window(
            bundle(), tmp_path,
            start="2026-01-01T01:00:00Z", end="2026-02-01",
        )


def test_window_allows_post_test_outcomes_but_marks_them(tmp_path):
    write_snapshot(tmp_path)
    window = resolve_backtest_window(
        bundle(), tmp_path,
        start="2026-02-01", end="2026-05-01",
    )
    assert window.uses_only_snapshot_test_split is False
    assert window.includes_post_test_period is True
