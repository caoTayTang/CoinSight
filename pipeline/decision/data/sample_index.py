"""Build one canonical sample index shared by tabular and sequence models."""
from __future__ import annotations

import numpy as np
import pandas as pd

SAMPLE_COLUMNS = (
    "sample_id", "symbol", "window_start_time", "latest_input_open_time",
    "cutoff_time", "target_time", "window_start_row", "window_end_row",
    "target_row", "reference_close_usdt", "actual_close_usdt",
    "target_log_return", "is_valid", "rejection_reason",
)


class SampleIndexBuilder:
    def build(
        self,
        candles: pd.DataFrame,
        features: pd.DataFrame,
        lookback: int = 168,
        horizon: int = 1,
        frequency: str = "1h",
    ) -> pd.DataFrame:
        if lookback <= 1 or horizon <= 0:
            raise ValueError("lookback must be greater than one and horizon must be positive")
        if frequency not in {"1h", "1d"}:
            raise ValueError("frequency must be either 1h or 1d")
        step = pd.Timedelta(hours=1) if frequency == "1h" else pd.Timedelta(days=1)
        if len(candles) != len(features):
            raise ValueError("candles and features must have identical row counts")
        required = {"symbol", "open_time", "close_price", "candle_valid", "feature_valid", "row_number"}
        if not required.issubset(features):
            raise ValueError(f"features are missing columns: {sorted(required - set(features))}")

        candle_keys = candles[["symbol", "open_time"]].copy()
        candle_keys["symbol"] = candle_keys["symbol"].astype(str).str.upper()
        candle_keys["open_time"] = pd.to_datetime(candle_keys["open_time"], utc=True)
        candle_keys = candle_keys.sort_values(["symbol", "open_time"]).reset_index(drop=True)
        feature_keys = features[["symbol", "open_time"]].copy()
        feature_keys["symbol"] = feature_keys["symbol"].astype(str).str.upper()
        feature_keys["open_time"] = pd.to_datetime(feature_keys["open_time"], utc=True)
        feature_keys = feature_keys.sort_values(["symbol", "open_time"]).reset_index(drop=True)
        if not candle_keys.equals(feature_keys):
            raise ValueError("candles and features do not describe the same timeline")

        rows: list[dict] = []
        frame = features.sort_values(["symbol", "open_time"]).reset_index(drop=True)
        for symbol, group in frame.groupby("symbol", sort=False):
            group = group.reset_index(drop=True)
            times = pd.to_datetime(group["open_time"], utc=True)
            for input_row in range(lookback, len(group) - horizon):
                raw_start = input_row - lookback
                window_start = input_row - lookback + 1
                target_row = input_row + horizon
                raw_slice = group.iloc[raw_start:target_row + 1]
                window = group.iloc[window_start:input_row + 1]
                expected_span = step * (lookback + horizon)
                continuous = (
                    len(raw_slice) == lookback + horizon + 1
                    and times.iloc[target_row] - times.iloc[raw_start] == expected_span
                    and times.iloc[raw_start:target_row + 1].diff().dropna().eq(step).all()
                )
                reason: str | None = None
                if not continuous:
                    reason = "missing_hour" if frequency == "1h" else "missing_day"
                elif not raw_slice["candle_valid"].all():
                    reason = "invalid_ohlc"
                elif not window["feature_valid"].all():
                    reason = "invalid_feature"
                reference = float(group.at[input_row, "close_price"])
                actual = float(group.at[target_row, "close_price"])
                target = np.log(actual / reference) if reference > 0 and actual > 0 else np.nan
                if not np.isfinite(target):
                    reason = reason or "missing_target"
                input_time = times.iloc[input_row]
                target_time = times.iloc[target_row]
                rows.append({
                    "sample_id": f"{symbol}:{target_time.isoformat()}",
                    "symbol": symbol,
                    "window_start_time": times.iloc[window_start],
                    "latest_input_open_time": input_time,
                    "cutoff_time": input_time + step,
                    "target_time": target_time,
                    "window_start_row": int(group.at[window_start, "row_number"]),
                    "window_end_row": int(group.at[input_row, "row_number"]),
                    "target_row": int(group.at[target_row, "row_number"]),
                    "reference_close_usdt": reference,
                    "actual_close_usdt": actual,
                    "target_log_return": float(target),
                    "is_valid": reason is None,
                    "rejection_reason": reason,
                })
        return pd.DataFrame(rows, columns=SAMPLE_COLUMNS)
