import numpy as np
import pandas as pd
import pytest

pytest.importorskip("xgboost")

from pipeline.decision.config import XGBoostConfig
from pipeline.decision.models.xgboost_regressor import XGBoostForecastModel
from pipeline.decision.types import TabularData


def tabular(values):
    X = np.asarray(values, dtype=np.float32).reshape(-1, 1)
    return TabularData(X, (X[:, 0] * 2).astype(np.float32), pd.DataFrame(), ("x",))


def test_xgboost_can_fit_save_load_and_preserve_predictions(tmp_path):
    config = XGBoostConfig(n_estimators=20, early_stopping_rounds=3, n_jobs=1)
    train = tabular(np.linspace(-1, 1, 40))
    validation = tabular(np.linspace(-0.9, 0.9, 20))
    model = XGBoostForecastModel(config)
    model.fit(train, validation)
    before = model.predict(validation)
    path = tmp_path / "model.ubj"
    model.save(path)

    loaded = XGBoostForecastModel.load(path, config, ("x",))
    assert np.allclose(loaded.predict(validation), before)
