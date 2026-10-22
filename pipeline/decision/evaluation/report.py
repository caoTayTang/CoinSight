"""Serialize evaluation reports and human-readable test diagnostics."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.decision.evaluation.evaluator import CandidateDecision, EvaluationReport


def write_evaluation_report(
    report: EvaluationReport,
    decision: CandidateDecision | None,
    directory: Path,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "split": report.split.value,
        "model": report.model.to_dict(),
        "zero_return": report.zero_return.to_dict(),
        "rolling_mean": report.rolling_mean.to_dict(),
        "persistence": (
            None if report.persistence is None else report.persistence.to_dict()
        ),
        "decision": None if decision is None else {
            "status": decision.status, "reasons": list(decision.reasons)
        },
    }
    (directory / f"{report.split.value}_metrics.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    report.monthly.to_csv(directory / f"{report.split.value}_monthly.csv", index=False)
    report.predictions.to_parquet(directory / f"{report.split.value}_predictions.parquet", index=False)


@dataclass(frozen=True)
class PredictedDirectionSummary:
    predicted_count: int
    correct_count: int
    incorrect_count: int
    correct_rate: float | None


@dataclass(frozen=True)
class DirectionDiagnostics:
    sample_count: int
    true_down_predicted_down: int
    true_down_predicted_up: int
    true_up_predicted_down: int
    true_up_predicted_up: int
    accuracy: float
    predicted_down: PredictedDirectionSummary
    predicted_up: PredictedDirectionSummary
    actual_down_recall: float | None
    actual_up_recall: float | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class QuantileDiagnostics:
    sample_count: int
    nominal_coverage: float
    empirical_coverage: float
    mean_interval_width: float
    lower_miss_rate: float
    upper_miss_rate: float
    confident_up_count: int
    confident_down_count: int
    uncertain_count: int
    confident_direction_accuracy: float | None

    def to_dict(self) -> dict:
        return asdict(self)


def _safe_rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def compute_direction_diagnostics(predictions: pd.DataFrame) -> DirectionDiagnostics:
    """Treat positive return as UP and zero/negative return as DOWN."""
    required = {"actual_log_return", "predicted_log_return"}
    missing = required - set(predictions)
    if missing:
        raise ValueError(f"predictions are missing columns: {sorted(missing)}")
    if predictions.empty:
        raise ValueError("direction diagnostics require at least one prediction")
    actual = predictions["actual_log_return"].to_numpy(dtype=np.float64)
    predicted = predictions["predicted_log_return"].to_numpy(dtype=np.float64)
    if not np.isfinite(actual).all() or not np.isfinite(predicted).all():
        raise ValueError("direction diagnostics cannot contain NaN or infinite values")

    actual_up = actual > 0
    predicted_up = predicted > 0
    tn = int((~actual_up & ~predicted_up).sum())
    fp = int((~actual_up & predicted_up).sum())
    fn = int((actual_up & ~predicted_up).sum())
    tp = int((actual_up & predicted_up).sum())
    total = len(actual)
    predicted_down_count = tn + fn
    predicted_up_count = tp + fp
    actual_down_count = tn + fp
    actual_up_count = tp + fn
    return DirectionDiagnostics(
        sample_count=total,
        true_down_predicted_down=tn,
        true_down_predicted_up=fp,
        true_up_predicted_down=fn,
        true_up_predicted_up=tp,
        accuracy=(tn + tp) / total,
        predicted_down=PredictedDirectionSummary(
            predicted_count=predicted_down_count,
            correct_count=tn,
            incorrect_count=fn,
            correct_rate=_safe_rate(tn, predicted_down_count),
        ),
        predicted_up=PredictedDirectionSummary(
            predicted_count=predicted_up_count,
            correct_count=tp,
            incorrect_count=fp,
            correct_rate=_safe_rate(tp, predicted_up_count),
        ),
        actual_down_recall=_safe_rate(tn, actual_down_count),
        actual_up_recall=_safe_rate(tp, actual_up_count),
    )


def compute_direction_head_diagnostics(
    predictions: pd.DataFrame,
) -> DirectionDiagnostics:
    """Evaluate a separate P(UP) head at its fixed 0.5 threshold."""
    required = {"actual_log_return", "direction_probability_up"}
    missing = required - set(predictions)
    if missing:
        raise ValueError(
            f"direction-head predictions are missing columns: {sorted(missing)}"
        )
    probabilities = predictions["direction_probability_up"].to_numpy(
        dtype=np.float64
    )
    if not np.isfinite(probabilities).all() or not (
        (probabilities >= 0) & (probabilities <= 1)
    ).all():
        raise ValueError("direction probabilities must be finite values in [0, 1]")
    frame = predictions[["actual_log_return"]].copy()
    frame["predicted_log_return"] = np.where(probabilities >= 0.5, 1.0, -1.0)
    return compute_direction_diagnostics(frame)


def compute_quantile_diagnostics(predictions: pd.DataFrame) -> QuantileDiagnostics:
    """Measure q10-q90 calibration and zero-excluding direction signals."""
    required = {"actual_log_return", "return_q10", "return_q50", "return_q90"}
    missing = required - set(predictions)
    if missing:
        raise ValueError(f"quantile predictions are missing columns: {sorted(missing)}")
    values = predictions[list(required)].to_numpy(dtype=np.float64)
    if not len(values) or not np.isfinite(values).all():
        raise ValueError("quantile diagnostics require finite predictions")
    actual = predictions["actual_log_return"].to_numpy(dtype=np.float64)
    q10 = predictions["return_q10"].to_numpy(dtype=np.float64)
    q50 = predictions["return_q50"].to_numpy(dtype=np.float64)
    q90 = predictions["return_q90"].to_numpy(dtype=np.float64)
    if not ((q10 <= q50) & (q50 <= q90)).all():
        raise ValueError("quantile predictions must satisfy q10 <= q50 <= q90")
    confident_up = q10 > 0
    confident_down = q90 < 0
    confident = confident_up | confident_down
    correct = (confident_up & (actual > 0)) | (confident_down & (actual <= 0))
    return QuantileDiagnostics(
        sample_count=len(actual),
        nominal_coverage=0.8,
        empirical_coverage=float(((actual >= q10) & (actual <= q90)).mean()),
        mean_interval_width=float(np.mean(q90 - q10)),
        lower_miss_rate=float((actual < q10).mean()),
        upper_miss_rate=float((actual > q90).mean()),
        confident_up_count=int(confident_up.sum()),
        confident_down_count=int(confident_down.sum()),
        uncertain_count=int((~confident).sum()),
        confident_direction_accuracy=(
            None if not confident.any() else float(correct[confident].mean())
        ),
    )


def _percent(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2%}"


def _plot_confusion_matrix(
    diagnostics: DirectionDiagnostics,
    destination: Path,
    title: str = "Test direction confusion matrix",
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    matrix = np.asarray([
        [
            diagnostics.true_down_predicted_down,
            diagnostics.true_down_predicted_up,
        ],
        [
            diagnostics.true_up_predicted_down,
            diagnostics.true_up_predicted_up,
        ],
    ])
    figure, axis = plt.subplots(figsize=(6.4, 5.2))
    image = axis.imshow(matrix, cmap="Blues")
    figure.colorbar(image, ax=axis, fraction=0.046, pad=0.04)
    axis.set_xticks((0, 1), labels=("Predicted DOWN", "Predicted UP"))
    axis.set_yticks((0, 1), labels=("Actual DOWN", "Actual UP"))
    axis.set_xlabel("Prediction")
    axis.set_ylabel("Ground truth")
    axis.set_title(title)
    threshold = matrix.max() / 2 if matrix.size else 0
    for row in range(2):
        for column in range(2):
            count = int(matrix[row, column])
            share = count / diagnostics.sample_count
            axis.text(
                column,
                row,
                f"{count}\n({share:.1%} of test)",
                ha="center",
                va="center",
                color="white" if count > threshold else "black",
            )
    figure.tight_layout()
    figure.savefig(destination, dpi=160, bbox_inches="tight")
    plt.close(figure)


def _plot_test_prices(predictions: pd.DataFrame, destination: Path) -> None:
    required = {"target_time", "actual_close_usdt", "predicted_close_usdt"}
    missing = required - set(predictions)
    if missing:
        raise ValueError(f"price plot is missing columns: {sorted(missing)}")
    frame = predictions.sort_values("target_time")
    actual = frame["actual_close_usdt"].to_numpy(dtype=np.float64)
    predicted = frame["predicted_close_usdt"].to_numpy(dtype=np.float64)
    if not np.isfinite(actual).all() or not np.isfinite(predicted).all():
        raise ValueError("price plot cannot contain NaN or infinite values")

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    target_time = pd.to_datetime(frame["target_time"], utc=True)
    figure, axis = plt.subplots(figsize=(14, 6))
    axis.plot(
        target_time,
        actual,
        label="Ground truth close",
        linewidth=2.0,
        color="#111827",
    )
    axis.plot(
        target_time,
        predicted,
        label="Predicted close",
        linewidth=1.5,
        color="#2563eb",
        alpha=0.85,
    )
    axis.set_title("One-step-ahead close forecast on the test split")
    axis.set_xlabel("Target candle")
    axis.set_ylabel("Close price (USDT)")
    axis.grid(alpha=0.25)
    axis.legend()
    figure.autofmt_xdate()
    figure.tight_layout()
    figure.savefig(destination, dpi=160, bbox_inches="tight")
    plt.close(figure)


def write_test_diagnostic_report(
    report: EvaluationReport,
    directory: Path,
    *,
    run_id: str,
    symbol: str,
    model_type: str,
) -> DirectionDiagnostics:
    """Write machine-readable and visual diagnostics for one consumed test."""
    if report.split.value != "test":
        raise ValueError("diagnostic report must be generated from the test split")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    diagnostics = compute_direction_diagnostics(report.predictions)
    (directory / "test_direction_metrics.json").write_text(
        json.dumps(diagnostics.to_dict(), indent=2), encoding="utf-8"
    )
    _plot_confusion_matrix(
        diagnostics, directory / "test_confusion_matrix.png"
    )
    _plot_test_prices(report.predictions, directory / "test_price_forecast.png")

    direction_head_section = ""
    if "direction_probability_up" in report.predictions:
        head = compute_direction_head_diagnostics(report.predictions)
        (directory / "test_direction_head_metrics.json").write_text(
            json.dumps(head.to_dict(), indent=2), encoding="utf-8"
        )
        _plot_confusion_matrix(
            head,
            directory / "test_direction_head_confusion_matrix.png",
            title="Test auxiliary direction-head confusion matrix",
        )
        direction_head_section = f"""
## Auxiliary direction head

The independent classification head predicts UP when `P(UP) >= 0.5`.
Its test accuracy is **{head.accuracy:.2%}**. This result is separate from the
direction implied by the return head and does not alter predicted prices.

![Auxiliary direction-head confusion matrix](test_direction_head_confusion_matrix.png)
"""

    quantile_section = ""
    if {"return_q10", "return_q50", "return_q90"}.issubset(report.predictions):
        quantile = compute_quantile_diagnostics(report.predictions)
        (directory / "test_quantile_metrics.json").write_text(
            json.dumps(quantile.to_dict(), indent=2), encoding="utf-8"
        )
        confident_accuracy = _percent(quantile.confident_direction_accuracy)
        quantile_section = f"""
## Quantile uncertainty

| Metric | Value |
| --- | ---: |
| q10-q90 nominal coverage | {quantile.nominal_coverage:.2%} |
| q10-q90 empirical coverage | {quantile.empirical_coverage:.2%} |
| Mean return interval width | {quantile.mean_interval_width:.4%} |
| Confident UP (`q10 > 0`) | {quantile.confident_up_count} |
| Confident DOWN (`q90 < 0`) | {quantile.confident_down_count} |
| Uncertain (interval crosses zero) | {quantile.uncertain_count} |
| Direction accuracy on confident samples | {confident_accuracy} |

This is an empirical uncertainty interval, not a calibrated probability.
"""

    down = diagnostics.predicted_down
    up = diagnostics.predicted_up
    persistence = report.persistence
    persistence_section = ""
    if persistence is not None:
        scale_ratio = (
            "N/A"
            if persistence.movement_scale_ratio is None
            else f"{persistence.movement_scale_ratio:.3f}"
        )
        persistence_section = f"""
## Persistence/copy diagnostics

| Metric | Value |
| --- | ---: |
| Mean absolute actual move | {persistence.mean_abs_actual_move:.4%} |
| Mean absolute predicted move | {persistence.mean_abs_predicted_move:.4%} |
| Movement scale ratio | {scale_ratio} |
| Copy rate (`move < {persistence.copy_threshold:.2%}`) | {persistence.copy_rate:.2%} |
| Samples beating persistence | {persistence.beat_persistence_rate:.2%} |

`movement_scale_ratio` near zero indicates that forecasts collapse toward the
previous close. `beat_persistence_rate` is the share of samples whose return
error is lower than predicting zero return.
"""
    matrix = [
        (
            diagnostics.true_down_predicted_down,
            diagnostics.true_down_predicted_up,
        ),
        (
            diagnostics.true_up_predicted_down,
            diagnostics.true_up_predicted_up,
        ),
    ]
    markdown = f"""# Test evaluation report

- Run: `{run_id}`
- Symbol: `{symbol}`
- Model: `{model_type}`
- Samples: `{diagnostics.sample_count}`
- Direction rule: return `> 0` is **UP**; return `<= 0` is **DOWN**.
- Test protocol: rolling one-step prediction using real candles available before each target. Predicted prices are not recursively fed into the following sample.

## Direction confusion matrix

| Ground truth \\ Prediction | DOWN | UP |
| --- | ---: | ---: |
| DOWN | {matrix[0][0]} ({matrix[0][0] / diagnostics.sample_count:.2%}) | {matrix[0][1]} ({matrix[0][1] / diagnostics.sample_count:.2%}) |
| UP | {matrix[1][0]} ({matrix[1][0] / diagnostics.sample_count:.2%}) | {matrix[1][1]} ({matrix[1][1] / diagnostics.sample_count:.2%}) |

Overall direction accuracy: **{diagnostics.accuracy:.2%}**.

![Direction confusion matrix](test_confusion_matrix.png)

## Correctness by predicted trend

| Predicted trend | Predictions | Correct | Incorrect | Correct rate |
| --- | ---: | ---: | ---: | ---: |
| DOWN | {down.predicted_count} | {down.correct_count} | {down.incorrect_count} | {_percent(down.correct_rate)} |
| UP | {up.predicted_count} | {up.correct_count} | {up.incorrect_count} | {_percent(up.correct_rate)} |

Actual-DOWN recall: **{_percent(diagnostics.actual_down_recall)}**.
Actual-UP recall: **{_percent(diagnostics.actual_up_recall)}**.

{direction_head_section}

{quantile_section}

{persistence_section}

## Regression metrics

| Candidate | MAE return | RMSE return | MAE price (USDT) | sMAPE price | Direction accuracy |
| --- | ---: | ---: | ---: | ---: | ---: |
| Model | {report.model.mae_return:.8f} | {report.model.rmse_return:.8f} | {report.model.mae_price_usdt:.4f} | {report.model.smape_price:.4%} | {report.model.directional_accuracy:.2%} |
| Zero return | {report.zero_return.mae_return:.8f} | {report.zero_return.rmse_return:.8f} | {report.zero_return.mae_price_usdt:.4f} | {report.zero_return.smape_price:.4%} | {report.zero_return.directional_accuracy:.2%} |
| Rolling mean | {report.rolling_mean.mae_return:.8f} | {report.rolling_mean.rmse_return:.8f} | {report.rolling_mean.mae_price_usdt:.4f} | {report.rolling_mean.smape_price:.4%} | {report.rolling_mean.directional_accuracy:.2%} |

## Predicted close versus ground truth

Each point is an independent one-step-ahead forecast for its `target_time`.

![Predicted and actual close](test_price_forecast.png)
"""
    (directory / "test_evaluation_report.md").write_text(
        markdown, encoding="utf-8"
    )
    return diagnostics
