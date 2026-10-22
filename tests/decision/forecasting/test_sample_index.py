import numpy as np

from pipeline.decision.data.feature_extractor import HourlyFeatureExtractor
from pipeline.decision.data.sample_index import SampleIndexBuilder
from tests.decision.forecasting.helpers import candles


def test_first_sample_uses_170_raw_candles_and_168_feature_rows():
    raw = candles(170)
    features = HourlyFeatureExtractor().transform(raw)

    [sample] = SampleIndexBuilder().build(raw, features).to_dict("records")

    assert sample["window_start_row"] == 1
    assert sample["window_end_row"] == 168
    assert sample["target_row"] == 169
    assert sample["latest_input_open_time"] == raw.loc[168, "open_time"]
    assert "input_open_time" not in sample
    assert sample["cutoff_time"] == sample["target_time"]
    assert sample["is_valid"]
    assert sample["target_log_return"] == np.log(
        raw.loc[169, "close_price"] / raw.loc[168, "close_price"]
    )


def test_sample_crossing_gap_is_rejected_not_imputed():
    raw = candles(171).drop(index=50).reset_index(drop=True)
    features = HourlyFeatureExtractor().transform(raw)
    samples = SampleIndexBuilder().build(raw, features)
    assert not samples.empty
    assert (~samples["is_valid"]).all()
    assert set(samples["rejection_reason"]) == {"missing_hour"}
