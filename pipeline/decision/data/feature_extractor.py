"""Leakage-safe per-candle features shared by every forecasting model."""
from __future__ import annotations

import numpy as np
import pandas as pd

BASE_FEATURES = (
    "log_return_1h",
    "open_close_return",
    "high_low_range",
    "close_position",
    "upper_wick",
    "lower_wick",
    "log_volume",
    "volume_change",
    "log_trade_count",
    "hour_sin",
    "hour_cos",
    "dow_sin",
    "dow_cos",
)

ROLLING_FEATURES = (
    "momentum_6h",
    "momentum_24h",
    "momentum_72h",
    "momentum_168h",
    "momentum_336h",
    "volatility_6h",
    "volatility_24h",
    "volatility_72h",
    "volatility_168h",
    "volatility_336h",
    "volume_zscore_24h",
    "volume_zscore_168h",
    "volume_zscore_336h",
    "volatility_ratio_24_168",
)

V1_SEQUENCE_FEATURES = BASE_FEATURES
V2_ASSET_FEATURES = BASE_FEATURES + ROLLING_FEATURES
SUPPORTED_FEATURE_VERSIONS = {
    "hourly-return-v1": V1_SEQUENCE_FEATURES,
    "hourly-return-v2": V2_ASSET_FEATURES,
}
MAX_ROLLING_WINDOW = 336

DAILY_BASE_FEATURES = (
    "log_return_1d",
    "open_close_return",
    "high_low_range",
    "close_position",
    "upper_wick",
    "lower_wick",
    "log_volume",
    "volume_change",
    "log_trade_count",
    "dow_sin",
    "dow_cos",
)

DAILY_ROLLING_FEATURES = (
    "momentum_7d",
    "momentum_14d",
    "momentum_30d",
    "momentum_60d",
    "momentum_90d",
    "volatility_7d",
    "volatility_14d",
    "volatility_30d",
    "volatility_60d",
    "volatility_90d",
    "volume_zscore_7d",
    "volume_zscore_30d",
    "volume_zscore_90d",
    "volatility_ratio_7_30",
)

DAILY_SEQUENCE_FEATURES = DAILY_BASE_FEATURES + DAILY_ROLLING_FEATURES
DAILY_MAX_ROLLING_WINDOW = 90
SUPPORTED_FEATURE_VERSIONS["daily-return-v1"] = DAILY_SEQUENCE_FEATURES
SUPPORTED_FEATURE_VERSIONS["daily-return-v2"] = DAILY_SEQUENCE_FEATURES

RAW_COLUMNS = (
    "symbol", "open_time", "open_price", "high_price", "low_price",
    "close_price", "volume_quote", "trade_count", "batch_id",
)


class HourlyFeatureExtractor:
    feature_version = "hourly-return-v1"

    def __init__(self, feature_version: str = "hourly-return-v1"):
        if feature_version not in {"hourly-return-v1", "hourly-return-v2"}:
            raise ValueError(f"unsupported feature version: {feature_version}")
        self.feature_version = feature_version

    def validate_candles(self, candles: pd.DataFrame) -> None:
        missing = set(RAW_COLUMNS) - set(candles.columns)
        if missing:
            raise ValueError(f"candles are missing columns: {sorted(missing)}")
        if candles.empty:
            raise ValueError("cannot extract features from an empty candle frame")
        times = pd.to_datetime(candles["open_time"], utc=True)
        duplicate_keys = pd.DataFrame({
            "symbol": candles["symbol"].astype(str).str.upper(), "open_time": times,
        }).duplicated()
        if duplicate_keys.any():
            raise ValueError("duplicate open_time values are not allowed per symbol")
        if not (times.dt.minute.eq(0) & times.dt.second.eq(0) & times.dt.microsecond.eq(0)).all():
            raise ValueError("hourly candles must be aligned to UTC hour boundaries")

    def transform(self, candles: pd.DataFrame) -> pd.DataFrame:
        self.validate_candles(candles)
        frame = candles.copy()
        frame["symbol"] = frame["symbol"].astype(str).str.upper()
        frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True)
        frame = frame.sort_values(["symbol", "open_time"]).reset_index(drop=True)
        frame["row_number"] = frame.groupby("symbol", sort=False).cumcount()

        numeric = [
            "open_price", "high_price", "low_price", "close_price",
            "volume_quote", "trade_count",
        ]
        for column in numeric:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        finite = np.isfinite(frame[numeric]).all(axis=1)
        positive_prices = frame[["open_price", "high_price", "low_price", "close_price"]].gt(0).all(axis=1)
        consistent = (
            frame["high_price"].ge(frame[["open_price", "low_price", "close_price"]].max(axis=1))
            & frame["low_price"].le(frame[["open_price", "close_price"]].min(axis=1))
        )
        non_negative = frame["volume_quote"].ge(0) & frame["trade_count"].ge(0)
        frame["candle_valid"] = finite & positive_prices & consistent & non_negative

        grouped = frame.groupby("symbol", sort=False, group_keys=False)
        previous_close = grouped["close_price"].shift(1)
        log_volume = np.log1p(frame["volume_quote"])
        previous_log_volume = grouped["volume_quote"].shift(1).pipe(np.log1p)
        previous_time = grouped["open_time"].shift(1)
        consecutive = frame["open_time"].sub(previous_time).eq(pd.Timedelta(hours=1))

        frame["log_return_1h"] = np.where(
            consecutive, np.log(frame["close_price"] / previous_close), np.nan
        )
        frame["open_close_return"] = np.log(frame["close_price"] / frame["open_price"])
        frame["high_low_range"] = np.log(frame["high_price"] / frame["low_price"])
        price_range = frame["high_price"] - frame["low_price"]
        frame["close_position"] = np.where(
            price_range.eq(0), 0.5,
            (frame["close_price"] - frame["low_price"]) / price_range,
        )
        frame["upper_wick"] = np.log(
            frame["high_price"] / frame[["open_price", "close_price"]].max(axis=1)
        )
        frame["lower_wick"] = np.log(
            frame[["open_price", "close_price"]].min(axis=1) / frame["low_price"]
        )
        frame["log_volume"] = log_volume
        frame["volume_change"] = np.where(consecutive, log_volume - previous_log_volume, np.nan)
        frame["log_trade_count"] = np.log1p(frame["trade_count"])
        hour = frame["open_time"].dt.hour
        weekday = frame["open_time"].dt.dayofweek
        frame["hour_sin"] = np.sin(2 * np.pi * hour / 24)
        frame["hour_cos"] = np.cos(2 * np.pi * hour / 24)
        frame["dow_sin"] = np.sin(2 * np.pi * weekday / 7)
        frame["dow_cos"] = np.cos(2 * np.pi * weekday / 7)
        target_features = list(BASE_FEATURES)
        if self.feature_version == "hourly-return-v2":
            segments = (~consecutive).groupby(frame["symbol"], sort=False).cumsum()
            segment_keys = [frame["symbol"], segments]
            for hours in (6, 24, 72, 168, 336):
                shifted_close = grouped["close_price"].shift(hours)
                shifted_time = grouped["open_time"].shift(hours)
                exact_lag = frame["open_time"].sub(shifted_time).eq(
                    pd.Timedelta(hours=hours)
                )
                frame[f"momentum_{hours}h"] = np.where(
                    exact_lag, np.log(frame["close_price"] / shifted_close), np.nan
                )
                frame[f"volatility_{hours}h"] = frame.groupby(
                    segment_keys, sort=False
                )["log_return_1h"].transform(
                    lambda values, window=hours: values.rolling(
                        window, min_periods=window
                    ).std(ddof=0)
                )
            for hours in (24, 168, 336):
                rolling = frame.groupby(segment_keys, sort=False)["log_volume"].rolling(
                    hours, min_periods=hours
                )
                mean = rolling.mean().reset_index(level=[0, 1], drop=True)
                std = rolling.std(ddof=0).reset_index(level=[0, 1], drop=True)
                frame[f"volume_zscore_{hours}h"] = np.where(
                    std.eq(0), 0.0, (frame["log_volume"] - mean) / std
                )
            frame["volatility_ratio_24_168"] = (
                frame["volatility_24h"] / frame["volatility_168h"]
            )
            target_features.extend(ROLLING_FEATURES)

        frame[target_features] = frame[target_features].replace([np.inf, -np.inf], np.nan)
        frame["feature_valid"] = (
            frame["candle_valid"] & frame[target_features].notna().all(axis=1)
        )
        return frame

    def feature_names(self) -> tuple[str, ...]:
        if self.feature_version == "hourly-return-v2":
            return BASE_FEATURES + ROLLING_FEATURES
        return BASE_FEATURES


class DailyFeatureExtractor:
    """Create features using only information available after each UTC day closes."""

    feature_version = "daily-return-v1"

    def __init__(self, feature_version: str = "daily-return-v1"):
        if feature_version not in {"daily-return-v1", "daily-return-v2"}:
            raise ValueError(f"unsupported daily feature version: {feature_version}")
        self.feature_version = feature_version

    def validate_candles(self, candles: pd.DataFrame) -> None:
        missing = set(RAW_COLUMNS) - set(candles.columns)
        if missing:
            raise ValueError(f"candles are missing columns: {sorted(missing)}")
        if candles.empty:
            raise ValueError("cannot extract features from an empty candle frame")
        times = pd.to_datetime(candles["open_time"], utc=True)
        keys = pd.DataFrame({
            "symbol": candles["symbol"].astype(str).str.upper(),
            "open_time": times,
        })
        if keys.duplicated().any():
            raise ValueError("duplicate open_time values are not allowed per symbol")
        aligned = (
            times.dt.hour.eq(0) & times.dt.minute.eq(0)
            & times.dt.second.eq(0) & times.dt.microsecond.eq(0)
        )
        if not aligned.all():
            raise ValueError("daily candles must be aligned to UTC day boundaries")

    def transform(self, candles: pd.DataFrame) -> pd.DataFrame:
        self.validate_candles(candles)
        frame = candles.copy()
        frame["symbol"] = frame["symbol"].astype(str).str.upper()
        frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True)
        frame = frame.sort_values(["symbol", "open_time"]).reset_index(drop=True)
        frame["row_number"] = frame.groupby("symbol", sort=False).cumcount()

        numeric = [
            "open_price", "high_price", "low_price", "close_price",
            "volume_quote", "trade_count",
        ]
        for column in numeric:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        finite = np.isfinite(frame[numeric]).all(axis=1)
        positive_prices = frame[
            ["open_price", "high_price", "low_price", "close_price"]
        ].gt(0).all(axis=1)
        consistent = (
            frame["high_price"].ge(
                frame[["open_price", "low_price", "close_price"]].max(axis=1)
            )
            & frame["low_price"].le(
                frame[["open_price", "close_price"]].min(axis=1)
            )
        )
        non_negative = frame["volume_quote"].ge(0) & frame["trade_count"].ge(0)
        frame["candle_valid"] = finite & positive_prices & consistent & non_negative

        grouped = frame.groupby("symbol", sort=False, group_keys=False)
        previous_close = grouped["close_price"].shift(1)
        previous_time = grouped["open_time"].shift(1)
        consecutive = frame["open_time"].sub(previous_time).eq(pd.Timedelta(days=1))
        log_volume = np.log1p(frame["volume_quote"])
        previous_log_volume = grouped["volume_quote"].shift(1).pipe(np.log1p)

        frame["log_return_1d"] = np.where(
            consecutive, np.log(frame["close_price"] / previous_close), np.nan
        )
        frame["open_close_return"] = np.log(frame["close_price"] / frame["open_price"])
        frame["high_low_range"] = np.log(frame["high_price"] / frame["low_price"])
        price_range = frame["high_price"] - frame["low_price"]
        frame["close_position"] = np.where(
            price_range.eq(0), 0.5,
            (frame["close_price"] - frame["low_price"]) / price_range,
        )
        frame["upper_wick"] = np.log(
            frame["high_price"] / frame[["open_price", "close_price"]].max(axis=1)
        )
        frame["lower_wick"] = np.log(
            frame[["open_price", "close_price"]].min(axis=1) / frame["low_price"]
        )
        frame["log_volume"] = log_volume
        frame["volume_change"] = np.where(
            consecutive, log_volume - previous_log_volume, np.nan
        )
        frame["log_trade_count"] = np.log1p(frame["trade_count"])
        weekday = frame["open_time"].dt.dayofweek
        frame["dow_sin"] = np.sin(2 * np.pi * weekday / 7)
        frame["dow_cos"] = np.cos(2 * np.pi * weekday / 7)

        segments = (~consecutive).groupby(frame["symbol"], sort=False).cumsum()
        segment_keys = [frame["symbol"], segments]
        for days in (7, 14, 30, 60, 90):
            shifted_close = grouped["close_price"].shift(days)
            shifted_time = grouped["open_time"].shift(days)
            exact_lag = frame["open_time"].sub(shifted_time).eq(
                pd.Timedelta(days=days)
            )
            frame[f"momentum_{days}d"] = np.where(
                exact_lag, np.log(frame["close_price"] / shifted_close), np.nan
            )
            frame[f"volatility_{days}d"] = frame.groupby(
                segment_keys, sort=False
            )["log_return_1d"].transform(
                lambda values, window=days: values.rolling(
                    window, min_periods=window
                ).std(ddof=0)
            )
        for days in (7, 30, 90):
            rolling = frame.groupby(segment_keys, sort=False)["log_volume"].rolling(
                days, min_periods=days
            )
            mean = rolling.mean().reset_index(level=[0, 1], drop=True)
            std = rolling.std(ddof=0).reset_index(level=[0, 1], drop=True)
            frame[f"volume_zscore_{days}d"] = np.where(
                std.eq(0), 0.0, (frame["log_volume"] - mean) / std
            )
        frame["volatility_ratio_7_30"] = (
            frame["volatility_7d"] / frame["volatility_30d"]
        )

        names = list(DAILY_SEQUENCE_FEATURES)
        frame[names] = frame[names].replace([np.inf, -np.inf], np.nan)
        frame["feature_valid"] = (
            frame["candle_valid"] & frame[names].notna().all(axis=1)
        )
        return frame

    def feature_names(self) -> tuple[str, ...]:
        return DAILY_SEQUENCE_FEATURES


def feature_extractor(feature_version: str):
    if feature_version.startswith("hourly-"):
        return HourlyFeatureExtractor(feature_version)
    if feature_version.startswith("daily-"):
        return DailyFeatureExtractor(feature_version)
    raise ValueError(f"unsupported feature version: {feature_version}")


def return_feature_name(feature_version: str) -> str:
    if feature_version.startswith("hourly-"):
        return "log_return_1h"
    if feature_version.startswith("daily-"):
        return "log_return_1d"
    raise ValueError(f"unsupported feature version: {feature_version}")


def feature_warmup_periods(feature_version: str) -> int:
    if feature_version == "hourly-return-v2":
        return MAX_ROLLING_WINDOW
    if feature_version in {"daily-return-v1", "daily-return-v2"}:
        return DAILY_MAX_ROLLING_WINDOW
    if feature_version == "hourly-return-v1":
        return 1
    raise ValueError(f"unsupported feature version: {feature_version}")


def asset_order(
    target_symbol: str,
    context_symbols: tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    """Return the stable target-first order used by train and inference."""
    target = str(target_symbol).upper()
    context = sorted({str(symbol).upper() for symbol in context_symbols} - {target})
    return (target, *context)


def fused_asset_feature_names(feature_version: str) -> tuple[str, ...]:
    """Return the per-asset columns used by a fused feature version."""
    if feature_version == "hourly-return-v2":
        return V2_ASSET_FEATURES
    if feature_version == "daily-return-v2":
        return DAILY_SEQUENCE_FEATURES
    raise ValueError(f"{feature_version} is not a fused feature version")


def is_fused_feature_version(feature_version: str) -> bool:
    return feature_version in {"hourly-return-v2", "daily-return-v2"}


def fused_sequence_feature_names(
    target_symbol: str,
    context_symbols: tuple[str, ...] | list[str],
    feature_version: str = "hourly-return-v2",
) -> tuple[str, ...]:
    asset_features = fused_asset_feature_names(feature_version)
    return tuple(
        f"{symbol}__{feature}"
        for symbol in asset_order(target_symbol, context_symbols)
        for feature in asset_features
    )


def fused_symbols_from_feature_names(
    feature_names: tuple[str, ...],
    feature_version: str = "hourly-return-v2",
) -> tuple[str, ...]:
    """Validate a fused layout and recover its ordered asset universe."""
    asset_features = fused_asset_feature_names(feature_version)
    width = len(asset_features)
    if not feature_names or len(feature_names) % width:
        raise ValueError(
            f"feature names do not describe a fused {feature_version} layout"
        )
    symbols: list[str] = []
    for offset in range(0, len(feature_names), width):
        chunk = feature_names[offset:offset + width]
        prefixes: list[str] = []
        suffixes: list[str] = []
        for name in chunk:
            if "__" not in name:
                raise ValueError(
                    f"feature names do not describe a fused {feature_version} layout"
                )
            prefix, suffix = name.split("__", 1)
            prefixes.append(prefix)
            suffixes.append(suffix)
        if len(set(prefixes)) != 1 or tuple(suffixes) != asset_features:
            raise ValueError(
                f"feature names do not describe a fused {feature_version} layout"
            )
        symbols.append(prefixes[0])
    if len(set(symbols)) != len(symbols):
        raise ValueError(f"fused {feature_version} layout contains duplicate symbols")
    return tuple(symbols)


def sequence_feature_names(
    feature_version: str,
    target_symbol: str | None = None,
    context_symbols: tuple[str, ...] | list[str] = (),
) -> tuple[str, ...]:
    if feature_version == "hourly-return-v1":
        return V1_SEQUENCE_FEATURES
    if feature_version == "hourly-return-v2":
        if target_symbol is None:
            raise ValueError("hourly-return-v2 feature names require target_symbol")
        return fused_sequence_feature_names(
            target_symbol, context_symbols, feature_version
        )
    if feature_version == "daily-return-v1":
        return DAILY_SEQUENCE_FEATURES
    if feature_version == "daily-return-v2":
        if target_symbol is None:
            raise ValueError("daily-return-v2 feature names require target_symbol")
        return fused_sequence_feature_names(
            target_symbol, context_symbols, feature_version
        )
    raise ValueError(f"unsupported feature version: {feature_version}")


class MultiAssetFeatureFusion:
    """Join the same per-asset features onto the target period timeline."""

    def attach(
        self,
        target_features: pd.DataFrame,
        context_candles: pd.DataFrame | None,
        target_symbol: str,
        context_symbols: tuple[str, ...] | list[str],
        feature_version: str = "hourly-return-v2",
    ) -> pd.DataFrame:
        asset_features = fused_asset_feature_names(feature_version)
        target_symbol = target_symbol.upper()
        expected_symbols = asset_order(target_symbol, context_symbols)[1:]
        context_features: pd.DataFrame | None = None
        if expected_symbols:
            if context_candles is None or context_candles.empty:
                raise ValueError(f"context candles are required for {feature_version}")
            context = context_candles.copy()
            context["symbol"] = context["symbol"].astype(str).str.upper()
            context = context[context["symbol"].isin(expected_symbols)]
            if context.empty:
                raise ValueError("no configured context symbols are present in context candles")
            present = set(context["symbol"].unique())
            missing = set(expected_symbols) - present
            if missing:
                raise ValueError(f"context candles are missing symbols: {sorted(missing)}")
            context_features = feature_extractor(feature_version).transform(context)
        result = target_features.copy()
        all_valid = result["feature_valid"].to_numpy(dtype=bool, copy=True)
        target_block = result.loc[:, list(asset_features)].rename(
            columns={name: f"{target_symbol}__{name}" for name in asset_features}
        ).reset_index(drop=True)
        fused_blocks = [target_block]
        target_times = pd.DataFrame({
            "open_time": pd.to_datetime(result["open_time"], utc=True)
        })
        for symbol in expected_symbols:
            assert context_features is not None
            coin = context_features.loc[
                context_features["symbol"].eq(symbol),
                ["open_time", "feature_valid", *asset_features],
            ].copy()
            renamed = {
                name: f"{symbol}__{name}" for name in asset_features
            }
            coin = coin.rename(columns=renamed)
            aligned = target_times.merge(
                coin, on="open_time", how="left", validate="one_to_one"
            )
            fused_blocks.append(
                aligned.loc[:, list(renamed.values())].reset_index(drop=True)
            )
            all_valid &= aligned["feature_valid"].eq(True).to_numpy(dtype=bool)

        names = fused_sequence_feature_names(
            target_symbol, expected_symbols, feature_version
        )
        result = pd.concat(
            [result.reset_index(drop=True), *fused_blocks], axis=1, copy=False
        )
        result[list(names)] = result[list(names)].replace([np.inf, -np.inf], np.nan)
        result["feature_valid"] = all_valid & result[list(names)].notna().all(axis=1)
        return result
