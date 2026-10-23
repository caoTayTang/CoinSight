import pytest

from pipeline.decision.models.factory import build_model
from pipeline.decision.types import ModelType


@pytest.mark.parametrize("model_type", [ModelType.PATCHTST, ModelType.ITRANSFORMER])
def test_transformer_models_are_explicitly_deferred(model_type):
    with pytest.raises(NotImplementedError, match="Transformer phase"):
        build_model(model_type)


def test_recurrent_forward_contract_when_torch_is_available():
    torch = pytest.importorskip("torch")
    from pipeline.decision.models.recurrent_regressor import GRURegressor, LSTMRegressor

    inputs = torch.randn(4, 168, 13)
    for model in (GRURegressor(), LSTMRegressor()):
        model.eval()
        output = model(inputs)
        assert output.shape == (4, 1)
        quantiles, direction_logits = model.forward_quantile_heads(inputs)
        assert quantiles.shape == (4, 3)
        assert torch.all(quantiles[:, 0] <= quantiles[:, 1])
        assert torch.all(quantiles[:, 1] <= quantiles[:, 2])
        assert torch.equal(output, quantiles[:, 1:2])
        assert direction_logits.shape == (4, 1)
        (quantiles.sum() + direction_logits.sum()).backward()
        assert all(parameter.grad is not None for parameter in model.parameters())


def test_historical_two_head_contract_is_still_supported():
    torch = pytest.importorskip("torch")
    from pipeline.decision.models.recurrent_regressor import GRURegressor

    model = GRURegressor(
        quantile_output=False, separate_direction_head=True
    )
    return_output, direction_logits = model.forward_heads(torch.randn(2, 10, 13))

    assert return_output.shape == (2, 1)
    assert direction_logits.shape == (2, 1)
