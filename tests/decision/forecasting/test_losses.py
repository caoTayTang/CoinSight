import pytest

torch = pytest.importorskip("torch")

from pipeline.decision.training.losses import (
    DirectionAwareRegressionLoss,
    QuantilePersistenceLoss,
)


def test_direction_loss_prefers_predictions_with_correct_sign():
    target = torch.tensor([[-1.0], [1.0]])
    correct = torch.tensor([[-2.0], [2.0]], requires_grad=True)
    wrong = torch.tensor([[2.0], [-2.0]])
    loss_fn = DirectionAwareRegressionLoss(direction_weight=0.1)

    correct_total, _, correct_direction, _ = loss_fn.components(correct, target)
    wrong_total, _, wrong_direction, _ = loss_fn.components(wrong, target)

    assert correct_direction < wrong_direction
    assert torch.isfinite(correct_total)
    correct_total.backward()
    assert torch.isfinite(correct.grad).all()


def test_separate_direction_logits_do_not_change_regression_or_persistence():
    prediction = torch.tensor([[0.2], [-0.2]], requires_grad=True)
    target = torch.tensor([[1.0], [-1.0]])
    correct_logits = torch.tensor([[2.0], [-2.0]], requires_grad=True)
    wrong_logits = -correct_logits.detach()
    loss_fn = DirectionAwareRegressionLoss(
        direction_weight=0.1,
        persistence_weight=1.0,
    )

    correct = loss_fn.components(prediction, target, correct_logits)
    wrong = loss_fn.components(prediction, target, wrong_logits)

    assert torch.equal(correct[1], wrong[1])
    assert torch.equal(correct[3], wrong[3])
    assert correct[2] < wrong[2]
    correct[0].backward()
    assert torch.isfinite(prediction.grad).all()
    assert torch.isfinite(correct_logits.grad).all()


def test_zero_direction_weight_is_exactly_huber_regression():
    prediction = torch.tensor([[-0.5], [0.5]])
    target = torch.tensor([[-1.0], [1.0]])
    total, huber, direction, persistence = DirectionAwareRegressionLoss(
        direction_weight=0.0, zero_scaled=0.25
    ).components(prediction, target)

    assert torch.equal(total, huber)
    assert torch.isfinite(direction)
    assert torch.isfinite(persistence)


def test_direction_loss_rejects_invalid_weight():
    with pytest.raises(ValueError, match="non-negative"):
        DirectionAwareRegressionLoss(direction_weight=float("nan"))


def test_persistence_ranking_rewards_beating_zero_return():
    target = torch.tensor([[-2.0], [2.0]])
    zero_return = torch.zeros_like(target)
    toward_target = target * 0.5
    loss_fn = DirectionAwareRegressionLoss(
        persistence_weight=1.0,
        persistence_margin_fraction=0.25,
    )

    _, _, _, zero_penalty = loss_fn.components(zero_return, target)
    _, _, _, improved_penalty = loss_fn.components(toward_target, target)

    assert zero_penalty > 0
    assert improved_penalty == 0


def test_persistence_ranking_ignores_moves_below_threshold():
    _, _, _, persistence = DirectionAwareRegressionLoss(
        persistence_weight=1.0,
        minimum_actual_move_scaled=0.1,
    ).components(torch.zeros(2, 1), torch.tensor([[-0.05], [0.05]]))

    assert persistence == 0


def test_quantile_loss_prefers_correct_ordered_forecasts():
    target = torch.tensor([[-1.0], [1.0]])
    correct = torch.tensor([
        [-1.5, -1.0, -0.5], [0.5, 1.0, 1.5]
    ], requires_grad=True)
    wrong = torch.tensor([
        [0.5, 1.0, 1.5], [-1.5, -1.0, -0.5]
    ])
    loss_fn = QuantilePersistenceLoss(persistence_weight=0.0)

    correct_total, q10, q50, q90, direction, _ = loss_fn.components(
        correct, target
    )
    wrong_total = loss_fn(wrong, target)

    assert correct_total < wrong_total
    assert all(torch.isfinite(value) for value in (q10, q50, q90, direction))
    correct_total.backward()
    assert torch.isfinite(correct.grad).all()


def test_quantile_persistence_uses_q50_only():
    target = torch.tensor([[-2.0], [2.0]])
    good_q50 = torch.tensor([[-5.0, -1.0, 5.0], [-5.0, 1.0, 5.0]])
    zero_q50 = torch.tensor([[-5.0, 0.0, 5.0], [-5.0, 0.0, 5.0]])
    loss_fn = QuantilePersistenceLoss(
        persistence_weight=1.0, persistence_margin_fraction=0.25
    )

    *_, good_penalty = loss_fn.components(good_q50, target)
    *_, zero_penalty = loss_fn.components(zero_q50, target)

    assert good_penalty == 0
    assert zero_penalty > 0


def test_quantile_logistic_loss_prefers_correct_direction_logits():
    target = torch.tensor([[-1.0], [1.0]])
    quantiles = torch.tensor([
        [-1.5, -1.0, -0.5], [0.5, 1.0, 1.5]
    ])
    correct_logits = torch.tensor([[-2.0], [2.0]], requires_grad=True)
    wrong_logits = -correct_logits.detach()
    loss_fn = QuantilePersistenceLoss(direction_weight=1.0)

    correct = loss_fn.components(quantiles, target, correct_logits)
    wrong = loss_fn.components(quantiles, target, wrong_logits)

    assert correct[4] < wrong[4]
    assert correct[0] < wrong[0]
    correct[0].backward()
    assert torch.isfinite(correct_logits.grad).all()
