import pandas as pd

from pipeline.decision.data.split import TimeSeriesSplitter
from pipeline.decision.types import SplitBoundaries


def test_split_is_assigned_by_target_time_at_exact_boundaries():
    targets = pd.to_datetime([
        "2024-12-31T23:00:00Z", "2025-01-01T00:00:00Z",
        "2025-12-31T23:00:00Z", "2026-01-01T00:00:00Z",
    ])
    samples = pd.DataFrame({
        "sample_id": [f"s{i}" for i in range(4)],
        "target_time": targets,
        "is_valid": True,
    })
    boundaries = SplitBoundaries(
        pd.Timestamp("2025-01-01T00:00:00Z"),
        pd.Timestamp("2026-01-01T00:00:00Z"),
        pd.Timestamp("2026-02-01T00:00:00Z"),
    )
    result = TimeSeriesSplitter().assign(samples, boundaries)
    assert result["split"].tolist() == ["train", "validation", "validation", "test"]
