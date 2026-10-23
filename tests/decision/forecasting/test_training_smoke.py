import pytest

torch = pytest.importorskip("torch")

from pipeline.decision.config import (
    TrainingConfig,
    recurrent_config_from_artifact,
    training_config_from_artifact,
)
from pipeline.decision.data.dataloader import ForecastDataModule
from pipeline.decision.models.recurrent_regressor import GRURegressor
from pipeline.decision.training.torch_trainer import TorchTrainer
from pipeline.decision.types import ModelType
from tests.decision.forecasting.test_dataloader import prepared_frames


def test_historical_training_config_does_not_enable_persistence_loss():
    config = training_config_from_artifact({"device": "cpu"})

    assert config.persistence_loss_weight == 0.0


def test_historical_recurrent_config_keeps_one_head_architecture():
    config = recurrent_config_from_artifact({"input_size": 13})

    assert config.separate_direction_head is False
    assert config.quantile_output is False
    assert config.quantile_logistic_head is False


def test_gru_training_smoke_returns_finite_checkpoint(capsys):
    features, samples = prepared_frames()
    module = ForecastDataModule.from_frames(
        features, samples, ModelType.GRU, batch_size=2, seed=42
    )
    module.setup()
    model = GRURegressor(hidden_size=4, dropout=0)
    trainer = TorchTrainer(TrainingConfig(
        batch_size=2, max_epochs=2, patience=2, seed=42, learning_rate=1e-3,
        device="cpu", progress_every_batches=1, direction_loss_weight=0.1,
    ))
    result = trainer.fit(model, module)
    predictions = trainer.predict(model, module, "validation")
    quantiles = trainer.predict_quantiles(
        model, module, "validation"
    )
    assert result.best_epoch is not None
    assert "train_quantile_loss" in result.history[0]
    assert "train_pinball_q10" in result.history[0]
    assert "train_pinball_q50" in result.history[0]
    assert "train_pinball_q90" in result.history[0]
    assert "train_persistence_ranking" in result.history[0]
    assert "validation_directional_accuracy" in result.history[0]
    assert "validation_interval_coverage" in result.history[0]
    assert "train_direction_bce" in result.history[0]
    assert "validation_direction_head_accuracy" in result.history[0]
    assert torch.isfinite(torch.as_tensor(predictions)).all()
    assert quantiles.shape == (len(predictions), 3)
    assert (quantiles[:, 0] <= quantiles[:, 1]).all()
    assert (quantiles[:, 1] <= quantiles[:, 2]).all()
    assert torch.allclose(
        torch.as_tensor(predictions), torch.as_tensor(quantiles[:, 1])
    )
    output = capsys.readouterr().out
    assert "[train] epoch 001/002 | batch 0001/0001" in output
    assert "[validation] epoch 001/002 | batch 0001/0001" in output
    assert "[epoch] 001/002" in output
    assert "[predict] split=validation | batch 0001/0001" in output


def test_gru_training_can_resume_from_last_completed_epoch(tmp_path, capsys):
    features, samples = prepared_frames()
    module = ForecastDataModule.from_frames(
        features, samples, ModelType.GRU, batch_size=2, seed=42
    )
    module.setup()
    first_model = GRURegressor(hidden_size=4, dropout=0)
    first = TorchTrainer(TrainingConfig(
        batch_size=2, max_epochs=1, patience=3, seed=42, learning_rate=1e-3,
        device="cpu", progress_every_batches=1,
    )).fit(first_model, module, checkpoint_dir=tmp_path)

    resumed_model = GRURegressor(hidden_size=4, dropout=0)
    resumed = TorchTrainer(TrainingConfig(
        batch_size=2, max_epochs=2, patience=3, seed=42, learning_rate=1e-3,
        device="cpu", progress_every_batches=1,
    )).fit(resumed_model, module, checkpoint_dir=tmp_path, resume=True)

    assert (tmp_path / "best_checkpoint.pt").exists()
    assert (tmp_path / "last_checkpoint.pt").exists()
    assert len(first.history) == 1
    assert len(resumed.history) == 2
    assert resumed.history[0] == first.history[0]
    assert "[resume] loaded epoch 1/2" in capsys.readouterr().out
