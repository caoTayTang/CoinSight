from __future__ import annotations

import json

import numpy as np
import pandas as pd

from pipeline.decision.evaluation.evaluator import (
    EvaluationReport,
    compute_persistence_diagnostics,
)
from pipeline.decision.evaluation.metrics import compute_metrics
from pipeline.decision.evaluation.report import (
    compute_direction_diagnostics,
    compute_direction_head_diagnostics,
    compute_quantile_diagnostics,
    write_test_diagnostic_report,
)
from pipeline.decision.train import resolve_snapshot_symbol
from pipeline.decision.types import DatasetSplit


def prediction_frame() -> pd.DataFrame:
    actual = np.asarray([-0.02, -0.01, -0.03, 0.01, 0.02, 0.03])
    predicted = np.asarray([-0.01, -0.02, 0.01, -0.01, 0.02, 0.01])
    reference = np.full(len(actual), 100.0)
    return pd.DataFrame({
        "sample_id": [f"BTC:{index}" for index in range(len(actual))],
        "symbol": "BTC",
        "target_time": pd.date_range(
            "2026-01-01", periods=len(actual), freq="D", tz="UTC"
        ),
        "actual_log_return": actual,
        "predicted_log_return": predicted,
        "reference_close_usdt": reference,
        "actual_close_usdt": reference * np.exp(actual),
        "predicted_close_usdt": reference * np.exp(predicted),
    })


def test_direction_diagnostics_explain_up_and_down_predictions():
    diagnostics = compute_direction_diagnostics(prediction_frame())

    assert diagnostics.true_down_predicted_down == 2
    assert diagnostics.true_down_predicted_up == 1
    assert diagnostics.true_up_predicted_down == 1
    assert diagnostics.true_up_predicted_up == 2
    assert diagnostics.accuracy == 4 / 6
    assert diagnostics.predicted_down.correct_count == 2
    assert diagnostics.predicted_down.incorrect_count == 1
    assert diagnostics.predicted_down.correct_rate == 2 / 3
    assert diagnostics.predicted_up.correct_count == 2
    assert diagnostics.predicted_up.incorrect_count == 1
    assert diagnostics.predicted_up.correct_rate == 2 / 3


def test_test_report_writes_markdown_json_and_plots(tmp_path):
    predictions = prediction_frame()
    predictions["direction_probability_up"] = np.asarray(
        [0.1, 0.2, 0.8, 0.2, 0.7, 0.9]
    )
    predictions["return_q10"] = predictions["predicted_log_return"] - 0.02
    predictions["return_q50"] = predictions["predicted_log_return"]
    predictions["return_q90"] = predictions["predicted_log_return"] + 0.02
    actual = predictions["actual_log_return"].to_numpy()
    predicted = predictions["predicted_log_return"].to_numpy()
    reference = predictions["reference_close_usdt"].to_numpy()
    zero = np.zeros(len(actual))
    zero_metrics = compute_metrics(actual, zero, reference)
    report = EvaluationReport(
        split=DatasetSplit.TEST,
        model=compute_metrics(actual, predicted, reference, zero_metrics.mae_return),
        zero_return=zero_metrics,
        rolling_mean=compute_metrics(
            actual, np.full(len(actual), 0.001), reference, zero_metrics.mae_return
        ),
        monthly=pd.DataFrame(),
        predictions=predictions,
        persistence=compute_persistence_diagnostics(actual, predicted),
    )

    write_test_diagnostic_report(
        report,
        tmp_path,
        run_id="run-1",
        symbol="BTC",
        model_type="gru",
    )

    expected = {
        "test_direction_metrics.json",
        "test_confusion_matrix.png",
        "test_price_forecast.png",
        "test_evaluation_report.md",
        "test_direction_head_metrics.json",
        "test_direction_head_confusion_matrix.png",
        "test_quantile_metrics.json",
    }
    assert expected.issubset({path.name for path in tmp_path.iterdir()})
    payload = json.loads(
        (tmp_path / "test_direction_metrics.json").read_text(encoding="utf-8")
    )
    assert payload["accuracy"] == 4 / 6
    markdown = (tmp_path / "test_evaluation_report.md").read_text(
        encoding="utf-8"
    )
    assert "Predicted trend" in markdown
    assert "not recursively fed" in markdown
    assert "Persistence/copy diagnostics" in markdown
    assert "Movement scale ratio" in markdown
    assert "Auxiliary direction head" in markdown
    assert "Quantile uncertainty" in markdown

    head = compute_direction_head_diagnostics(predictions)
    assert head.accuracy == 4 / 6
    quantile = compute_quantile_diagnostics(predictions)
    assert quantile.sample_count == 6
    assert quantile.nominal_coverage == 0.8


def test_snapshot_symbol_is_inferred_only_when_unique(tmp_path):
    root = tmp_path / "snapshots"
    btc = root / "snapshot-1" / "BTC"
    btc.mkdir(parents=True)
    (btc / "manifest.json").write_text("{}", encoding="utf-8")

    assert resolve_snapshot_symbol(root, "snapshot-1", None) == "BTC"
    assert resolve_snapshot_symbol(root, "snapshot-1", "btc") == "BTC"
