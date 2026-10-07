from __future__ import annotations

from datetime import date, datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field


T = TypeVar("T")


class Provenance(BaseModel):
    source: str
    mode: Literal["historical", "live", "replay", "metadata"]
    grain: str | None = None
    observed_at: datetime | None = None
    computed_at: datetime | None = None
    batch_id: int | None = None
    model_version: str | None = None


class Quality(BaseModel):
    freshness_seconds: int | None = None
    sample_count: int | None = None
    warnings: list[str] = Field(default_factory=list)


class Envelope(BaseModel, Generic[T]):
    status: Literal["ready", "stale", "insufficient_data", "unavailable"]
    data: T | None
    provenance: Provenance
    quality: Quality
    trace_id: str


class Snapshot(BaseModel):
    symbol: str
    as_of_date: date
    close_price_usdt: float
    volume_quote_usdt: float


class LiveMetric(BaseModel):
    symbol: str
    source: str
    window_start: datetime
    window_end: datetime
    avg_price_usdt: float
    price_volatility_usdt: float
    total_volume_quote: float
    event_count: int


class LiveSummary(BaseModel):
    symbol: str
    window_start: datetime
    window_end: datetime
    last_candle_at: datetime
    close_price_usdt: float
    change_pct: float
    volume_quote_usdt: float
    observed_minutes: int
    expected_minutes: int = 15


class DirectionPrediction(BaseModel):
    symbol: str
    as_of_date: date
    target_date: date
    probability_up: float = Field(ge=0, le=1)
    model_version: str
    baseline_brier_score: float
    model_brier_score: float


class ModelEvaluation(BaseModel):
    feature_version: str
    cutoff_date: date
    decision: Literal["accepted", "rejected"]
    train_rows: int
    validation_rows: int
    test_rows: int
    validation_brier: float | None
    baseline_validation_brier: float | None
    test_brier: float | None
    baseline_test_brier: float | None
    model_version: str | None


class BatchLineage(BaseModel):
    load_batch: dict
    extract_batches: list[dict]
    source_files: list[dict]


class DataStatus(BaseModel):
    latest_batch_id: int | None
    latest_batch_status: str | None
    latest_batch_finished_at: datetime | None
    rejected_rows: int | None
    dq_warnings: list[dict]
