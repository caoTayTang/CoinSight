"""Validated candle context and deterministic, past-only anomaly detector."""

from datetime import datetime, timedelta, timezone
from typing import Annotated
import hashlib, json
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class Candle(BaseModel):
    model_config = ConfigDict(extra='forbid')
    open_time: datetime
    open_price: Positive
    high_price: Positive
    low_price: Positive
    close_price: Positive
    volume_quote: Nonnegative
    trade_count: Annotated[int, Field(ge=0)]

    @field_validator('open_time')
    @classmethod
    def aligned(cls, value):
        if value.tzinfo is None or value.minute or value.second or value.microsecond:
            raise ValueError('Candle timestamps must be timezone-aware aligned hours')
        return value.astimezone(timezone.utc)

    @model_validator(mode='after')
    def valid_prices(self):
        if self.high_price < max(self.open_price, self.close_price, self.low_price) or self.low_price > min(
            self.open_price, self.close_price, self.high_price
        ):
            raise ValueError('Invalid OHLC bounds')
        return self


class CandleContext(BaseModel):
    model_config = ConfigDict(extra='forbid')
    cutoff: datetime
    candles: Annotated[list[Candle], Field(min_length=169, max_length=169)]

    @field_validator('cutoff')
    @classmethod
    def aligned(cls, value):
        return Candle.aligned(value)

    @model_validator(mode='after')
    def contiguous(self):
        if self.cutoff > datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0):
            raise ValueError('Context must contain closed candles, not a future cutoff')
        expected = [self.cutoff - timedelta(hours=169 - i) for i in range(169)]
        if [c.open_time for c in self.candles] != expected:
            raise ValueError('Need exactly 169 ordered, contiguous closed candles before cutoff')
        return self


def context_digest(context: CandleContext) -> str:
    raw = json.dumps(context.model_dump(mode='json'), sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(raw).hexdigest()


def detect_anomalies(context: CandleContext) -> dict:
    """Score the latest closed bar against earlier bars; no label or forecast is used."""
    close = np.array([c.close_price for c in context.candles])
    returns = np.diff(np.log(close))
    volume = np.log1p([c.volume_quote for c in context.candles])
    ranges = np.array([(c.high_price - c.low_price) / c.open_price for c in context.candles])
    checks = []
    for name, values, floor in [
        ('log_return', returns, 1e-6),
        ('log_quote_volume', volume, 1e-3),
        ('range_fraction', ranges, 1e-6),
    ]:
        if not np.isfinite(values).all():
            raise ValueError('Non-finite derived anomaly metric')
        history, current = values[:-1], float(values[-1])
        median = float(np.median(history))
        mad = float(np.median(np.abs(history - median)))
        scale = max(1.4826 * mad, floor)
        z = (current - median) / scale
        if not np.isfinite([median, scale, z]).all():
            raise ValueError('Non-finite anomaly score')
        # Wide/quiet regimes may both merit inspection; no event or direction probability is inferred.
        checks.append(
            dict(
                metric=name,
                value=current,
                history_median=median,
                history_n=len(history),
                robust_z=float(z),
                robust_scale=scale,
                threshold=6.0,
                flagged=abs(z) >= 6.0,
                direction='above' if z >= 0 else 'below',
            )
        )
    return dict(
        agent='anomaly',
        context_sha256=context_digest(context),
        method='median_mad_closed_hour_v1',
        cutoff=context.cutoff.isoformat(),
        inspected_candle_open=context.candles[-1].open_time.isoformat(),
        is_anomaly=any(c['flagged'] for c in checks),
        checks=checks,
        interpretation='Statistical deviation from previous closed bars; not a trained event classifier or probability.',
    )
