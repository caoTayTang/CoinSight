import numpy as np
import pandas as pd
import pytest

from pipeline.decision.data.dataloader import ForecastDataModule
from pipeline.decision.data.feature_extractor import (
    HourlyFeatureExtractor,
    MultiAssetFeatureFusion,
    fused_sequence_feature_names,
)
from pipeline.decision.data.sample_index import SampleIndexBuilder
from pipeline.decision.types import DatasetSplit, ModelType
from tests.decision.forecasting.helpers import candles, feature_samples


def prepared_frames():
    _, features, samples = feature_samples(175)
    samples = samples.copy()
    samples["split"] = ["train", "train", "validation", "validation", "test", "test"]
    return features, samples


def test_xgboost_loader_returns_tabular_features():
    features, samples = prepared_frames()
    module = ForecastDataModule.from_frames(features, samples, ModelType.XGBOOST)
    module.setup()

    train = module.tabular(DatasetSplit.TRAIN)
    assert train.X.shape == (2, 78)
    assert train.y.shape == (2,)
    assert module.input_shape() == (78,)
    with pytest.raises(TypeError):
        module.dataset(DatasetSplit.TRAIN)


@pytest.mark.parametrize(
    ("model_type", "shape"),
    [
        (ModelType.GRU, (168, 13)),
        (ModelType.LSTM, (168, 13)),
        (ModelType.PATCHTST, (13, 168)),
        (ModelType.ITRANSFORMER, (168, 13)),
    ],
)
def test_sequence_loader_layouts_share_sample_ids(model_type, shape):
    features, samples = prepared_frames()
    module = ForecastDataModule.from_frames(features, samples, model_type)
    module.setup()

    window, target = module.dataset(DatasetSplit.TEST)[0]
    assert window.shape == shape
    assert target.shape == (1,)
    assert module.input_shape() == shape
    assert module.metadata(DatasetSplit.TEST)["sample_id"].tolist() == samples.iloc[4:]["sample_id"].tolist()
    with pytest.raises(TypeError):
        module.tabular(DatasetSplit.TRAIN)


def test_sequence_targets_are_standardized_from_training_split_only():
    features, samples = prepared_frames()
    module = ForecastDataModule.from_frames(features, samples, ModelType.GRU)
    module.setup()

    scaled_train = np.asarray([
        module.dataset(DatasetSplit.TRAIN)[index][1][0]
        for index in range(len(module.dataset(DatasetSplit.TRAIN)))
    ])
    assert np.isclose(scaled_train.mean(), 0.0, atol=1e-6)
    assert np.isclose(scaled_train.std(), 1.0, atol=1e-6)
    assert np.allclose(
        module.target_scaler.inverse_transform(scaled_train),
        module.targets(DatasetSplit.TRAIN),
    )


def test_sequence_loader_exposes_worker_and_pinned_memory_settings():
    features, samples = prepared_frames()
    module = ForecastDataModule.from_frames(
        features,
        samples,
        ModelType.GRU,
        num_workers=2,
        pin_memory=True,
    )
    module.setup()

    loader = module.dataloader(DatasetSplit.TRAIN)

    assert loader.num_workers == 2
    assert loader.pin_memory is True
    assert loader.persistent_workers is True


def test_v2_recurrent_loader_fuses_all_assets_and_uses_336_hour_windows():
    raw = candles(700)
    context_frames = []
    for symbol, multiplier in (("ETH", 1.1), ("SOL", 0.9)):
        frame = candles(700).copy()
        frame["symbol"] = symbol
        for column in ("open_price", "high_price", "low_price", "close_price"):
            frame[column] *= multiplier
        context_frames.append(frame)
    target_features = HourlyFeatureExtractor("hourly-return-v2").transform(raw)
    features = MultiAssetFeatureFusion().attach(
        target_features,
        pd.concat(context_frames, ignore_index=True),
        "BTC",
        ("BTC", "ETH", "SOL"),
    )
    samples = SampleIndexBuilder().build(raw, features, lookback=336)
    valid = samples[samples["is_valid"]].head(6).copy()
    valid["split"] = ["train", "train", "validation", "validation", "test", "test"]

    module = ForecastDataModule.from_frames(
        features, valid, ModelType.GRU, feature_version="hourly-return-v2"
    )
    module.setup()

    names = fused_sequence_feature_names("BTC", ("ETH", "SOL"))
    assert len(names) == 81
    assert module.input_shape() == (336, 81)
    assert module.scaler.feature_names == names
