"""The DSS handoff must distinguish a scored candidate from a published forecast."""
from datetime import datetime, timedelta, timezone

from app import api


def test_prediction_returns_published_probability_and_model_evidence(monkeypatch):
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    monkeypatch.setattr(api, "fetch_all", lambda *_: [{
        "symbol": "BTC", "as_of_date": yesterday,
        "target_date": yesterday + timedelta(days=1),
        "probability_up": 0.61, "generated_at": datetime.now(timezone.utc),
        "model_version": "direction-daily-hourly-v1-20260930",
        "brier_score": 0.22, "baseline_brier_score": 0.25,
    }])

    response = api.direction_prediction("btc")

    assert response.status == "ready"
    assert response.data.symbol == "BTC"
    assert response.data.target_date == yesterday + timedelta(days=1)
    assert response.data.probability_up == 0.61
    assert response.provenance.model_version == response.data.model_version
    assert response.data.model_brier_score < response.data.baseline_brier_score


def test_rejected_candidate_is_visible_without_publishing_prediction(monkeypatch):
    evaluated_at = datetime.now(timezone.utc)

    def fetch(sql, *_):
        if "from meta.model_evaluation" in sql:
            return [{
                "feature_version": "daily-hourly-v1", "cutoff_date": evaluated_at.date(),
                "evaluated_at": evaluated_at, "decision": "rejected",
                "train_rows": 500, "validation_rows": 90, "test_rows": 90,
                "validation_brier": 0.27, "baseline_validation_brier": 0.25,
                "test_brier": None, "baseline_test_brier": None, "model_version": None,
            }]
        return []

    monkeypatch.setattr(api, "fetch_all", fetch)

    evaluation = api.model_evaluation()
    prediction = api.direction_prediction("BTC")

    assert evaluation.status == "ready"  # The evaluation record exists.
    assert evaluation.data.decision == "rejected"
    assert evaluation.quality.warnings
    assert prediction.status == "insufficient_data"
    assert prediction.data is None
