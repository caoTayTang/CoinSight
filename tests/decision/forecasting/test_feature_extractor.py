import numpy as np
import pandas as pd

from pipeline.decision.data.feature_extractor import (
    BASE_FEATURES,
    V2_ASSET_FEATURES,
    HourlyFeatureExtractor,
    MultiAssetFeatureFusion,
    fused_sequence_feature_names,
)
from tests.decision.forecasting.helpers import candles


def test_feature_formulas_and_flat_candle_position():
    frame = candles(3)
    frame.loc[1, ["open_price", "high_price", "low_price", "close_price"]] = 100.0
    result = HourlyFeatureExtractor().transform(frame)

    assert tuple(HourlyFeatureExtractor().feature_names()) == BASE_FEATURES
    assert result.loc[1, "close_position"] == 0.5
    assert result.loc[1, "log_return_1h"] == np.log(100 / frame.loc[0, "close_price"])
    assert result.loc[1, "open_close_return"] == 0
    assert result.loc[1, "high_low_range"] == 0


def test_future_mutation_does_not_change_past_features():
    frame = candles(10)
    extractor = HourlyFeatureExtractor()
    before = extractor.transform(frame)
    changed = frame.copy()
    changed.loc[9, ["open_price", "high_price", "low_price", "close_price"]] *= 2
    after = extractor.transform(changed)
    pd.testing.assert_frame_equal(
        before.loc[:8, list(BASE_FEATURES)], after.loc[:8, list(BASE_FEATURES)]
    )


def test_feature_after_gap_does_not_compute_multi_hour_return():
    frame = candles(5).drop(index=2).reset_index(drop=True)
    result = HourlyFeatureExtractor().transform(frame)
    assert np.isnan(result.loc[2, "log_return_1h"])
    assert np.isnan(result.loc[2, "volume_change"])


def _context_candles(count: int = 750) -> pd.DataFrame:
    frames = []
    for symbol, multiplier in (("ETH", 1.2), ("SOL", 0.8)):
        frame = candles(count).copy()
        frame["symbol"] = symbol
        for column in ("open_price", "high_price", "low_price", "close_price"):
            frame[column] *= multiplier
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def test_v2_fuses_same_features_for_every_asset_without_future_leakage():
    target = candles(750)
    context = _context_candles(750)
    extractor = HourlyFeatureExtractor("hourly-return-v2")
    target_features = extractor.transform(target)
    before = MultiAssetFeatureFusion().attach(
        target_features, context, "BTC", ("BTC", "ETH", "SOL")
    )

    names = fused_sequence_feature_names("BTC", ("ETH", "SOL"))
    assert len(V2_ASSET_FEATURES) == 27
    assert len(names) == 81
    assert set(names).issubset(before.columns)
    assert before.loc[336, "feature_valid"]
    expected_volatility = before.loc[313:336, "log_return_1h"].std(ddof=0)
    assert np.isclose(before.loc[336, "BTC__volatility_24h"], expected_volatility)
    assert np.isclose(
        before.loc[336, "BTC__momentum_336h"],
        np.log(target.loc[336, "close_price"] / target.loc[0, "close_price"]),
    )

    changed = context.copy()
    future = changed["open_time"] > target.loc[450, "open_time"]
    changed.loc[future, ["open_price", "high_price", "low_price", "close_price"]] *= 2
    after = MultiAssetFeatureFusion().attach(
        extractor.transform(target), changed, "BTC", ("BTC", "ETH", "SOL")
    )
    pd.testing.assert_frame_equal(
        before.loc[:450, list(names)],
        after.loc[:450, list(names)],
    )


def test_v2_supports_target_only_fusion():
    target = candles(700)
    target_features = HourlyFeatureExtractor("hourly-return-v2").transform(target)

    result = MultiAssetFeatureFusion().attach(
        target_features, pd.DataFrame(), "BTC", ("BTC",)
    )
    names = fused_sequence_feature_names("BTC", ("BTC",))

    assert len(names) == 27
    assert set(names).issubset(result.columns)
    assert result.loc[336, "feature_valid"]
    assert np.isclose(
        result.loc[336, "BTC__momentum_336h"],
        np.log(target.loc[336, "close_price"] / target.loc[0, "close_price"]),
    )
