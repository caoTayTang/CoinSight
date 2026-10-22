import pandas as pd
import pytest

from pipeline.decision.data.coverage import CoverageAuditor
from tests.decision.forecasting.helpers import candles


def test_coverage_groups_consecutive_missing_hours():
    frame = candles(6).drop(index=[2, 3])
    start = frame.open_time.min()
    end = start + pd.Timedelta(hours=6)

    report = CoverageAuditor().audit(frame, start, end, "BTC")

    assert report.row_count == 4
    assert len(report.missing_ranges) == 1
    assert report.missing_ranges[0].start == (start + pd.Timedelta(hours=2)).to_pydatetime()
    assert report.missing_ranges[0].end == (start + pd.Timedelta(hours=4)).to_pydatetime()
    with pytest.raises(ValueError, match="2 missing hours"):
        CoverageAuditor().assert_trainable(report)


def test_coverage_detects_duplicate_natural_key():
    frame = pd.concat([candles(3), candles(3).iloc[[1]]], ignore_index=True)
    report = CoverageAuditor().audit(
        frame, frame.open_time.min(), frame.open_time.max() + pd.Timedelta(hours=1), "BTC"
    )
    assert report.duplicate_count == 1
