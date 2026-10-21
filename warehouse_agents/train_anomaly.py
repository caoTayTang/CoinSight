"""One fixed Isolation Forest; temporal calibration and retrospective evaluation, never tune 2026."""

from pathlib import Path
import shutil
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from warehouse_agents.anomaly import features, FEATURES
from pipeline.decision.hourly_future import seal, unseal, digest

SOURCE = Path('data/models/hourly-mae-research/10926c36-fec5-412a-9185-9d5e44e8479a')
TEST = Path('data/models/hourly-2026-evaluation/7e5b9fed-17f8-483d-bcd2-356df60024e1')
OUT = Path('data/models/warehouse-anomaly/v1')


def run():
    if OUT.exists():
        raise ValueError('Training run already exists; do not overwrite frozen artifacts')
    snapshot = SOURCE / 'development_snapshot.csv'
    expected = unseal(SOURCE / 'plan.json')['source_snapshot_sha256']
    assert digest(snapshot.read_bytes()) == expected
    OUT.mkdir(parents=True)
    plan = dict(
        train_start='2023-01-01T00:00:00Z',
        train_end_exclusive='2025-01-01T00:00:00Z',
        calibration_start='2025-01-01T00:00:00Z',
        calibration_end_exclusive='2026-01-01T00:00:00Z',
        split_by='candle close / detection cutoff; detected bar is already closed',
        test='2026 saved snapshot, retrospective previously viewed',
        feature_names=FEATURES,
        config=dict(n_estimators=256, max_samples=512, contamination='auto', random_state=42, n_jobs=2),
        alert_budget_quantile=0.99,
        threshold_policy='2025 score quantile, method higher, locked before test',
        snapshot_sha256=expected,
        test_snapshot_sha256=digest((TEST / 'btc_snapshot.csv').read_bytes()),
        labels_used=False,
        hyperparameter_search=False,
        baseline='past-only median/MAD threshold abs(z)>=6',
        scheduler=False,
        claim='No precision/recall/accuracy without labeled real anomalies',
    )
    seal(OUT / 'plan.json', plan)
    shutil.copy2(__file__, OUT / 'train_anomaly.py')
    shutil.copy2('warehouse_agents/anomaly.py', OUT / 'anomaly.py')
    raw = pd.read_csv(snapshot, float_precision='round_trip')
    raw.open_time = pd.to_datetime(raw.open_time, utc=True)
    x = features(raw).dropna()
    cutoff = x.index + pd.Timedelta(hours=1)
    train = x[
        (cutoff >= pd.Timestamp(plan['train_start'])) & (cutoff < pd.Timestamp(plan['train_end_exclusive']))
    ]
    cal = x[
        (cutoff >= pd.Timestamp(plan['calibration_start']))
        & (cutoff < pd.Timestamp(plan['calibration_end_exclusive']))
    ]
    model = IsolationForest(**plan['config']).fit(train)
    threshold = float(np.quantile(-model.score_samples(cal), 0.99, method='higher'))
    profile = {}
    for col in FEATURES:
        v = train[col].to_numpy()
        edges = np.unique(np.quantile(v, np.arange(0.1, 1, 0.1)))
        counts = np.histogram(v, bins=[-np.inf, *edges, np.inf])[0]
        profile[col] = dict(
            median=float(np.median(v)),
            iqr=float(np.quantile(v, 0.75) - np.quantile(v, 0.25)),
            inner_edges=edges.tolist(),
            bin_fractions=(counts / counts.sum()).tolist(),
        )
    joblib.dump(model, OUT / 'isolation_forest.joblib')
    seal(
        OUT / 'model.json',
        dict(
            features=FEATURES,
            threshold=threshold,
            reference_profile=profile,
            train_n=len(train),
            calibration_n=len(cal),
            model_sha256=digest((OUT / 'isolation_forest.joblib').read_bytes()),
            plan_sha256=digest((OUT / 'plan.json').read_bytes()),
        ),
    )
    test_raw = pd.read_csv(TEST / 'btc_snapshot.csv', float_precision='round_trip')
    test_raw.open_time = pd.to_datetime(test_raw.open_time, utc=True)
    tx = features(test_raw).dropna()
    tc = tx.index + pd.Timedelta(hours=1)
    tx = tx[(tc >= pd.Timestamp('2026-01-01', tz='UTC')) & (tc < pd.Timestamp('2026-10-19', tz='UTC'))]
    # Detection cutoff, not next-hour forecast label: align exactly with original 2026 forecast cutoffs.
    wanted = pd.to_datetime(pd.read_csv(TEST / 'predictions.csv').cutoff_time, utc=True)
    tx = tx.reindex(pd.DatetimeIndex(wanted) - pd.Timedelta(hours=1))
    assert not tx.isna().any().any()
    scores = -model.score_samples(tx)
    reloaded = joblib.load(OUT / 'isolation_forest.joblib')
    np.testing.assert_array_equal(scores, -reloaded.score_samples(tx))
    rows = tx.copy()
    rows['cutoff'] = tx.index + pd.Timedelta(hours=1)
    rows['score'] = scores
    rows['flagged'] = scores >= threshold
    # Independent univariate baseline on the exact same 169-bar contexts.
    from agents.domain import CandleContext, detect_anomalies

    baseline = []
    for cutoff in rows.cutoff:
        context = test_raw[
            test_raw.open_time.ge(cutoff - pd.Timedelta(hours=169)) & test_raw.open_time.lt(cutoff)
        ]
        baseline.append(
            detect_anomalies(CandleContext(cutoff=cutoff, candles=context.to_dict('records')))['is_anomaly']
        )
    rows['mad_flagged'] = baseline
    rows.to_csv(OUT / 'test_scores.csv', index=False, float_format='%.17g')
    months = []
    for month, g in rows.groupby(rows.cutoff.dt.strftime('%Y-%m')):
        months.append(
            dict(
                month=month, n=len(g), forest_alerts=int(g.flagged.sum()), mad_alerts=int(g.mad_flagged.sum())
            )
        )
    report = dict(
        train_n=len(train),
        calibration_n=len(cal),
        test_n=len(tx),
        threshold=threshold,
        calibration_alert_rate=float(np.mean(-model.score_samples(cal) >= threshold)),
        test_alerts=int(rows.flagged.sum()),
        test_alert_rate=float(rows.flagged.mean()),
        mad_test_alerts=int(rows.mad_flagged.sum()),
        mad_test_alert_rate=float(rows.mad_flagged.mean()),
        monthly=months,
        top_events=rows.nlargest(10, 'score')[['cutoff', 'score', 'flagged']]
        .assign(cutoff=lambda d: d.cutoff.astype(str))
        .to_dict('records'),
        test_scores_sha256=digest((OUT / 'test_scores.csv').read_bytes()),
        reload_verified=True,
        accuracy=None,
        precision=None,
        recall=None,
        limitation='No labeled real anomalies. Alert rates are not accuracy or false-positive rates.',
    )
    seal(OUT / 'report.json', report)
    print(report, flush=True)


if __name__ == '__main__':
    run()
