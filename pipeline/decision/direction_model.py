"""Pooled 24-hour direction model, trained only from closed warehouse candles.

Prediction target: next UTC daily close > current UTC daily close. This is a
research decision aid, not an execution signal. Holdout dates are never used
for feature fitting or candidate selection.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from pipeline.settings import DATABASE_URL, DSS
from pipeline.decision.feature_builder import SYMBOLS, NUMERIC, load_features, labelled_rows

FEATURE_VERSION = "daily-hourly-v1"
MODEL_PATH = Path(os.getenv("DSS_MODEL_PATH", "/models/direction.joblib"))






def make_pipeline() -> Pipeline:
    return Pipeline([
        ("features", ColumnTransformer([
            ("numeric", StandardScaler(), list(NUMERIC)),
            ("symbol", OneHotEncoder(handle_unknown="ignore"), ["symbol"]),
        ])),
        ("classifier", LogisticRegression(max_iter=1000, random_state=42)),
    ])


def record_evaluation(database_url: str, cutoff: date, train_rows: int,
                      validation_rows: int, test_rows: int, validation_brier: float,
                      baseline_validation_brier: float, decision: str,
                      test_brier: float | None = None,
                      baseline_test_brier: float | None = None,
                      model_version: str | None = None) -> None:
    import psycopg2

    with psycopg2.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute("""insert into meta.model_evaluation (
            feature_version, cutoff_date, train_rows, validation_rows, test_rows,
            validation_brier, baseline_validation_brier, test_brier,
            baseline_test_brier, decision, model_version
        ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (FEATURE_VERSION, cutoff, train_rows, validation_rows, test_rows,
             float(validation_brier), float(baseline_validation_brier),
             float(test_brier) if test_brier is not None else None,
             float(baseline_test_brier) if baseline_test_brier is not None else None,
             decision, model_version))


def train(database_url: str = DATABASE_URL, model_path: Path = MODEL_PATH) -> dict:
    import psycopg2

    rows = labelled_rows(load_features(database_url))
    days = sorted(rows["day"].unique())
    minimum_days = DSS["minimum_history_days"]
    validation_days = DSS["validation_days"]
    test_days = DSS["test_days"]
    if len(days) < minimum_days or rows["symbol"].nunique() < len(SYMBOLS):
        return {"status": "insufficient_data", "reason":
                f"Need at least {minimum_days} aligned daily observations for {', '.join(SYMBOLS)}"}
    # The last test period stays untouched; the preceding period is validation.
    validation_start, test_start = days[-(validation_days + test_days)], days[-test_days]
    # The label for day D is tomorrow's close; omit the boundary day so no
    # training label reaches into validation or test.
    fit = rows[rows.day < validation_start - pd.Timedelta(days=1)]
    validation = rows[(rows.day >= validation_start) & (rows.day < test_start)]
    test = rows[rows.day >= test_start]
    if min(len(fit), len(validation), len(test)) == 0 or fit.target.nunique() < 2:
        return {"status": "insufficient_data", "reason": "Chronological train/validation/test split is incomplete"}
    candidate = make_pipeline().fit(fit, fit.target)
    validation_prob = candidate.predict_proba(validation)[:, 1]
    prevalence = float(fit.target.mean())
    validation_brier = brier_score_loss(validation.target, validation_prob)
    baseline_validation = brier_score_loss(validation.target, np.full(len(validation), prevalence))
    if validation_brier >= baseline_validation:
        record_evaluation(database_url, fit.day.max().date(), len(fit), len(validation),
                          len(test), validation_brier, baseline_validation, "rejected")
        return {"status": "rejected", "validation_brier": float(validation_brier),
                "baseline_validation_brier": float(baseline_validation)}
    training = rows[rows.day < test_start - pd.Timedelta(days=1)]
    model = make_pipeline().fit(training, training.target)
    test_prob = model.predict_proba(test)[:, 1]
    baseline = float(training.target.mean())
    brier = brier_score_loss(test.target, test_prob)
    baseline_brier = brier_score_loss(test.target, np.full(len(test), baseline))
    accuracy = accuracy_score(test.target, test_prob >= 0.5)
    baseline_accuracy = accuracy_score(test.target, np.full(len(test), baseline >= 0.5))
    if brier >= baseline_brier:
        record_evaluation(database_url, training.day.max().date(), len(training),
                          len(validation), len(test), validation_brier,
                          baseline_validation, "rejected", brier, baseline_brier)
        return {"status": "rejected", "test_brier": float(brier),
                "baseline_test_brier": float(baseline_brier)}
    cutoff = pd.Timestamp(training.day.max()).to_pydatetime().replace(tzinfo=timezone.utc)
    version = f"direction-{FEATURE_VERSION}-{cutoff:%Y%m%d}"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = model_path.with_suffix(".tmp")
    joblib.dump({"model": model, "version": version, "feature_version": FEATURE_VERSION}, temporary)
    digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
    temporary.replace(model_path)
    with psycopg2.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute("""insert into dw.dim_model (
            model_version, feature_version, training_cutoff, artifact_sha256,
            brier_score, baseline_brier_score, accuracy, baseline_accuracy
        ) values (%s,%s,%s,%s,%s,%s,%s,%s)
        on conflict (model_version) do update set artifact_sha256 = excluded.artifact_sha256,
            brier_score = excluded.brier_score, baseline_brier_score = excluded.baseline_brier_score,
            accuracy = excluded.accuracy, baseline_accuracy = excluded.baseline_accuracy""",
            (version, FEATURE_VERSION, cutoff, digest, float(brier), float(baseline_brier),
             float(accuracy), float(baseline_accuracy)))
    record_evaluation(database_url, training.day.max().date(), len(training),
                      len(validation), len(test), validation_brier,
                      baseline_validation, "accepted", brier, baseline_brier, version)
    return {"status": "accepted", "model_version": version, "test_brier": float(brier),
            "baseline_test_brier": float(baseline_brier), "accuracy": float(accuracy)}


def predict(database_url: str = DATABASE_URL, model_path: Path = MODEL_PATH) -> dict:
    import psycopg2

    if not model_path.exists():
        return {"status": "unavailable", "reason": "No accepted model artifact"}
    digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
    artifact = joblib.load(model_path)  # Trusted local artifact only.
    frame = load_features(database_url)
    if frame.empty:
        return {"status": "insufficient_data"}
    latest = frame.sort_values("day").groupby("symbol").tail(1).dropna(subset=list(NUMERIC))
    if len(latest) != len(SYMBOLS):
        return {"status": "insufficient_data", "reason": "All model symbols need complete features"}
    if latest.day.nunique() != 1 or latest.day.iloc[0].date() != datetime.now(timezone.utc).date() - timedelta(days=1):
        return {"status": "stale", "reason": "Latest closed daily candle is missing"}
    probabilities = artifact["model"].predict_proba(latest)[:, 1]
    with psycopg2.connect(database_url) as connection, connection.cursor() as cursor:
        cursor.execute("select model_key from dw.dim_model where model_version = %s and artifact_sha256 = %s",
                       (artifact["version"], digest))
        result = cursor.fetchone()
        if not result:
            raise ValueError("model artifact is not registered with matching checksum")
        model_key = result[0]
        for row, probability in zip(latest.itertuples(), probabilities):
            as_of = row.day.date()
            target = as_of + timedelta(days=1)
            cursor.execute("""insert into dw.fact_direction_prediction
                (asset_key, as_of_date_key, target_date_key, model_key, probability_up, feature_source)
                select asset_key, %s, %s, %s, %s, 'warehouse' from dw.dim_asset where symbol = %s
                on conflict (asset_key, as_of_date_key, target_date_key, model_key)
                do update set probability_up = excluded.probability_up, generated_at = now()
                returning prediction_id""",
                (int(as_of.strftime('%Y%m%d')), int(target.strftime('%Y%m%d')), model_key,
                 float(probability), row.symbol))
            prediction_id = cursor.fetchone()[0]
            cursor.execute("""insert into meta.prediction_batch_lineage (prediction_id, load_batch_id)
                values (%s, %s) on conflict do nothing""", (prediction_id, row.batch_id))
    return {"status": "ready", "model_version": artifact["version"], "predictions": len(latest)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("train", "predict"))
    args = parser.parse_args()
    print(train() if args.action == "train" else predict())
