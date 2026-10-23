"""GRU and LSTM regressors with a shared architecture contract."""
from __future__ import annotations

from typing import Literal

try:
    import torch
    from torch import nn
except ImportError as error:  # pragma: no cover - exercised only without optional dependency
    raise RuntimeError("PyTorch is required for GRU/LSTM forecast models") from error


class RecurrentRegressor(nn.Module):
    def __init__(
        self,
        cell_type: Literal["gru", "lstm"],
        input_size: int = 13,
        hidden_size: int = 64,
        num_layers: int = 1,
        dropout: float = 0.1,
        separate_direction_head: bool = False,
        quantile_output: bool = True,
        quantile_logistic_head: bool | None = None,
    ):
        super().__init__()
        if cell_type not in {"gru", "lstm"}:
            raise ValueError("cell_type must be 'gru' or 'lstm'")
        if input_size <= 0 or hidden_size <= 0 or num_layers <= 0:
            raise ValueError("model dimensions must be positive")
        self.cell_type = cell_type
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.separate_direction_head = bool(separate_direction_head)
        self.quantile_output = bool(quantile_output)
        self.quantile_logistic_head = (
            self.quantile_output
            if quantile_logistic_head is None
            else bool(quantile_logistic_head)
        )
        if self.quantile_output and self.separate_direction_head:
            raise ValueError("quantile output cannot use a separate direction head")
        if self.quantile_logistic_head and not self.quantile_output:
            raise ValueError("quantile logistic head requires quantile output")
        recurrent_dropout = dropout if num_layers > 1 else 0.0
        recurrent = nn.GRU if cell_type == "gru" else nn.LSTM
        self.encoder = recurrent(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=recurrent_dropout,
            batch_first=True,
            bidirectional=False,
        )
        self.dropout = nn.Dropout(dropout)
        # Keep the historical name ``head`` for checkpoint compatibility. It
        # remains the only output used to reconstruct the predicted price.
        self.head = nn.Linear(hidden_size, 1)
        # The central head is q50. Positive distances guarantee
        # q10 <= q50 <= q90 without a post-processing sort.
        self.interval_head = (
            nn.Linear(hidden_size, 2) if self.quantile_output else None
        )
        self.direction_head = (
            nn.Linear(hidden_size, 1) if self.separate_direction_head else None
        )
        # Logistic regression over q10/q50/q90. Quantiles are detached before
        # entering this layer so direction BCE cannot distort return forecasts.
        self.quantile_direction_head = (
            nn.Linear(3, 1) if self.quantile_logistic_head else None
        )

    @property
    def has_direction_head(self) -> bool:
        return self.direction_head is not None or self.quantile_direction_head is not None

    def _encoded_state(self, x: torch.Tensor) -> torch.Tensor:
        if x.ndim != 3 or x.shape[-1] != self.input_size:
            raise ValueError(
                f"expected [batch, sequence, {self.input_size}], got {tuple(x.shape)}"
            )
        _, hidden = self.encoder(x)
        if self.cell_type == "lstm":
            hidden = hidden[0]
        return self.dropout(hidden[-1])

    def forward_heads(
        self, x: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor | None]:
        """Return standardized return and optional up/down classification logit."""
        encoded = self._encoded_state(x)
        return_prediction = self.head(encoded)
        direction_logit = (
            None if self.direction_head is None else self.direction_head(encoded)
        )
        return return_prediction, direction_logit

    def forward_quantile_heads(
        self, x: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor | None]:
        """Return quantiles and an optional logistic UP/DOWN logit."""
        if self.interval_head is None:
            raise ValueError("model is not configured for quantile output")
        encoded = self._encoded_state(x)
        q50 = self.head(encoded)
        distances = torch.nn.functional.softplus(self.interval_head(encoded))
        quantiles = torch.cat(
            (q50 - distances[:, :1], q50, q50 + distances[:, 1:]), dim=1
        )
        direction_logit = (
            None
            if self.quantile_direction_head is None
            else self.quantile_direction_head(quantiles.detach())
        )
        return quantiles, direction_logit

    def forward_quantiles(self, x: torch.Tensor) -> torch.Tensor:
        """Return standardized [q10, q50, q90] forecasts."""
        return self.forward_quantile_heads(x)[0]

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Preserve the point-forecast contract: output q50/scalar return."""
        if self.quantile_output:
            return self.forward_quantiles(x)[:, 1:2]
        return_prediction, _ = self.forward_heads(x)
        return return_prediction


class GRURegressor(RecurrentRegressor):
    def __init__(self, **kwargs):
        super().__init__("gru", **kwargs)


class LSTMRegressor(RecurrentRegressor):
    def __init__(self, **kwargs):
        super().__init__("lstm", **kwargs)
