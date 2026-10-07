import pandas as pd

from pipeline.decision.feature_builder import labelled_rows


def test_labelled_rows_require_next_calendar_day():
    first = pd.Timestamp('2026-01-01')
    frame = pd.DataFrame({
        'day': [first, first + pd.Timedelta(days=2)],
        'next_day': [first + pd.Timedelta(days=2), pd.NaT],
        'next_close': [101.0, None],
        'return_1d': [0.01, 0.02], 'return_7d': [0.01, 0.02],
        'range_pct': [0.01, 0.02], 'volume_change': [0.01, 0.02],
        'hourly_range': [0.01, 0.02],
    })
    assert labelled_rows(frame).empty
