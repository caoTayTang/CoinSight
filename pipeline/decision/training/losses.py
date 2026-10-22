"""Loss functions for recurrent return forecasting."""
from __future__ import annotations

import math

try:
    import torch
    from torch import nn
    from torch.nn import functional as F
except ImportError as error:  # pragma: no cover - optional dependency boundary
    raise RuntimeError("PyTorch is required for recurrent forecast losses") from error


class DirectionAwareRegressionLoss(nn.Module):
    """Huber regression with direction and persistence-ranking penalties.

    Predictions and targets are standardized returns. ``zero_scaled`` is the
    standardized value corresponding to a raw log-return of zero. Persistence
    predicts that centered return as zero; the ranking term asks the model to
    improve on its error by a target-relative margin without rewarding an
    arbitrary non-zero forecast.
    """

    def __init__(
        self,
        direction_weight: float = 0.0,
        zero_scaled: float = 0.0,
        persistence_weight: float = 0.0,
        persistence_margin_fraction: float = 0.25,
        minimum_actual_move_scaled: float = 0.0,
    ):
        super().__init__()
        if not math.isfinite(direction_weight) or direction_weight < 0:
            raise ValueError("direction_weight must be non-negative")
        if not math.isfinite(zero_scaled):
            raise ValueError("zero_scaled must be finite")
        if not math.isfinite(persistence_weight) or persistence_weight < 0:
            raise ValueError("persistence_weight must be non-negative")
        if (
            not math.isfinite(persistence_margin_fraction)
            or not 0 <= persistence_margin_fraction <= 1
        ):
            raise ValueError("persistence_margin_fraction must be in [0, 1]")
        if (
            not math.isfinite(minimum_actual_move_scaled)
            or minimum_actual_move_scaled < 0
        ):
            raise ValueError("minimum_actual_move_scaled must be non-negative")
        self.direction_weight = float(direction_weight)
        self.zero_scaled = float(zero_scaled)
        self.persistence_weight = float(persistence_weight)
        self.persistence_margin_fraction = float(persistence_margin_fraction)
        self.minimum_actual_move_scaled = float(minimum_actual_move_scaled)

    def components(
        self,
        prediction: torch.Tensor,
        target: torch.Tensor,
        direction_logits: torch.Tensor | None = None,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        if prediction.shape != target.shape:
            raise ValueError("prediction and target shapes must match")
        if direction_logits is not None and direction_logits.shape != target.shape:
            raise ValueError("direction logits and target shapes must match")
        regression = F.huber_loss(prediction, target)
        direction_target = (target > self.zero_scaled).to(prediction.dtype)
        # Historical one-head checkpoints use centered return as their logit.
        # New recurrent models provide an independent classification logit.
        if direction_logits is None:
            direction_logits = prediction - self.zero_scaled
        direction = F.binary_cross_entropy_with_logits(
            direction_logits, direction_target
        )
        centered_target = target - self.zero_scaled
        centered_prediction = prediction - self.zero_scaled
        persistence_error = centered_target.abs()
        model_error = (centered_prediction - centered_target).abs()
        margin = self.persistence_margin_fraction * persistence_error
        ranking = F.relu(model_error - persistence_error + margin)
        eligible = persistence_error >= self.minimum_actual_move_scaled
        persistence = (
            ranking[eligible].mean()
            if eligible.any()
            else prediction.sum() * 0.0
        )
        total = (
            regression
            + self.direction_weight * direction
            + self.persistence_weight * persistence
        )
        return total, regression, direction, persistence

    def forward(
        self,
        prediction: torch.Tensor,
        target: torch.Tensor,
        direction_logits: torch.Tensor | None = None,
    ) -> torch.Tensor:
        total, _, _, _ = self.components(
            prediction, target, direction_logits
        )
        return total


class QuantilePersistenceLoss(nn.Module):
    """Pinball loss for q10/q50/q90 plus persistence ranking on q50."""

    quantiles = (0.1, 0.5, 0.9)

    def __init__(
        self,
        zero_scaled: float = 0.0,
        persistence_weight: float = 0.0,
        persistence_margin_fraction: float = 0.25,
        minimum_actual_move_scaled: float = 0.0,
    ):
        super().__init__()
        if not math.isfinite(zero_scaled):
            raise ValueError("zero_scaled must be finite")
        if not math.isfinite(persistence_weight) or persistence_weight < 0:
            raise ValueError("persistence_weight must be non-negative")
        if not 0 <= persistence_margin_fraction <= 1:
            raise ValueError("persistence_margin_fraction must be in [0, 1]")
        if minimum_actual_move_scaled < 0:
            raise ValueError("minimum_actual_move_scaled must be non-negative")
        self.zero_scaled = float(zero_scaled)
        self.persistence_weight = float(persistence_weight)
        self.persistence_margin_fraction = float(persistence_margin_fraction)
        self.minimum_actual_move_scaled = float(minimum_actual_move_scaled)

    @staticmethod
    def _pinball(
        prediction: torch.Tensor, target: torch.Tensor, quantile: float
    ) -> torch.Tensor:
        error = target - prediction
        return torch.maximum(quantile * error, (quantile - 1.0) * error).mean()

    def components(
        self, prediction: torch.Tensor, target: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        if prediction.ndim != 2 or prediction.shape[1] != 3:
            raise ValueError("quantile prediction must have shape [batch, 3]")
        if target.ndim == 1:
            target = target[:, None]
        if target.ndim != 2 or target.shape[1] != 1:
            raise ValueError("target must have shape [batch, 1]")
        if len(target) != len(prediction):
            raise ValueError("prediction and target batch sizes must match")
        q10, q50, q90 = (prediction[:, index:index + 1] for index in range(3))
        losses = tuple(
            self._pinball(value, target, quantile)
            for value, quantile in zip((q10, q50, q90), self.quantiles)
        )
        quantile_loss = sum(losses) / len(losses)
        persistence_error = (target - self.zero_scaled).abs()
        model_error = (q50 - target).abs()
        margin = self.persistence_margin_fraction * persistence_error
        ranking = F.relu(model_error - persistence_error + margin)
        eligible = persistence_error >= self.minimum_actual_move_scaled
        persistence = (
            ranking[eligible].mean()
            if eligible.any()
            else prediction.sum() * 0.0
        )
        total = quantile_loss + self.persistence_weight * persistence
        return total, losses[0], losses[1], losses[2], persistence

    def forward(self, prediction: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        return self.components(prediction, target)[0]
