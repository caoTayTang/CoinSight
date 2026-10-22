import numpy as np

from pipeline.decision.data.scaler import SequenceScaler, TargetScaler


def test_scaler_uses_only_values_passed_to_fit(tmp_path):
    train = np.asarray([[1.0, 10.0], [3.0, 14.0]])
    validation = np.asarray([[1_000_000.0, 2_000_000.0]])
    scaler = SequenceScaler(("a", "b")).fit(train)

    assert scaler.mean_.tolist() == [2.0, 12.0]
    assert np.allclose(scaler.transform(train).mean(axis=0), 0)
    assert np.abs(scaler.transform(validation)).min() > 1000

    path = tmp_path / "scaler.json"
    scaler.save(path)
    loaded = SequenceScaler.load(path)
    assert np.allclose(loaded.transform(train), scaler.transform(train))


def test_target_scaler_round_trips_training_targets(tmp_path):
    train = np.asarray([-0.01, 0.0, 0.02], dtype=np.float64)
    scaler = TargetScaler().fit(train)

    scaled = scaler.transform(train)
    assert np.isclose(scaled.mean(), 0.0, atol=1e-7)
    assert np.isclose(scaled.std(), 1.0, atol=1e-7)
    assert np.allclose(scaler.inverse_transform(scaled), train)

    path = tmp_path / "target_scaler.json"
    scaler.save(path)
    loaded = TargetScaler.load(path)
    assert np.allclose(loaded.inverse_transform(loaded.transform(train)), train)
