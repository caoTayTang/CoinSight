"""Trainable, causal BTC market anomaly features and read-only scoring."""

from functools import lru_cache
from pathlib import Path
import hashlib, json, os, io
import joblib
import numpy as np
import pandas as pd
from pipeline.decision.hourly_features import prepare_grid

FEATURES = [
    'return_z',
    'body_z',
    'range_ratio',
    'volume_z',
    'trades_z',
    'momentum6_z',
    'volatility_ratio6',
    'close_position',
    'upper_wick_fraction',
    'lower_wick_fraction',
]
MODEL_DIR = Path(os.getenv('ANOMALY_MODEL_DIR', 'data/models/warehouse-anomaly/v1'))


def features(raw):
    _, v, valid = prepare_grid(raw)
    o, h, l, c, q, t = (
        v[k] for k in ['open_price', 'high_price', 'low_price', 'close_price', 'volume_quote', 'trade_count']
    )
    r = np.log(c / c.shift())
    pastvol = r.shift().rolling(167, min_periods=167).std(ddof=0).clip(lower=1e-6)
    ranges = (h - l) / o
    past_range = ranges.shift().rolling(168, min_periods=168).median().clip(lower=1e-6)
    out = pd.DataFrame(index=v.index)
    out['return_z'] = r / pastvol
    out['body_z'] = np.log(c / o) / pastvol
    out['range_ratio'] = ranges / past_range
    for name, values in [('volume_z', np.log1p(q)), ('trades_z', np.log1p(t))]:
        past = values.shift()
        mean = past.rolling(168, min_periods=168).mean()
        std = past.rolling(168, min_periods=168).std(ddof=0).clip(lower=0.05)
        out[name] = (values - mean) / std
    out['momentum6_z'] = np.log(c / c.shift(6)) / (pastvol * np.sqrt(6))
    out['volatility_ratio6'] = r.rolling(6, min_periods=6).std(ddof=0) / pastvol
    span = (h - l).replace(0, np.nan)
    out['close_position'] = ((c - l) / span).fillna(0.5)
    out['upper_wick_fraction'] = ((h - pd.concat([o, c], axis=1).max(axis=1)) / span).fillna(0)
    out['lower_wick_fraction'] = ((pd.concat([o, c], axis=1).min(axis=1) - l) / span).fillna(0)
    full = valid.rolling(169, min_periods=169).sum().eq(169)
    return out[FEATURES].replace([np.inf, -np.inf], np.nan).where(full)


def read_record(path):
    record = json.loads(Path(path).read_text())
    payload = record['payload']
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if hashlib.sha256(encoded).hexdigest() != record['sha256']:
        raise ValueError('Artifact checksum mismatch')
    return payload


@lru_cache(maxsize=1)
def load_model():
    meta = read_record(MODEL_DIR / 'model.json')
    read_record(MODEL_DIR / 'plan.json')
    if hashlib.sha256((MODEL_DIR / 'plan.json').read_bytes()).hexdigest() != meta['plan_sha256']:
        raise ValueError('Anomaly plan mismatch')
    blob = (MODEL_DIR / 'isolation_forest.joblib').read_bytes()
    if hashlib.sha256(blob).hexdigest() != meta['model_sha256'] or meta['features'] != FEATURES:
        raise ValueError('Anomaly artifact mismatch')
    return joblib.load(io.BytesIO(blob)), meta


def score(raw):
    x = features(raw).iloc[[-1]]
    if x.isna().any().any():
        raise ValueError('Need 169 complete BTC candles')
    model, meta = load_model()
    value = float(-model.score_samples(x)[0])
    threshold = meta['threshold']
    profile = meta['reference_profile']
    deviations = []
    for col in FEATURES:
        p = profile[col]
        v = float(x[col].iloc[0])
        z = (v - p['median']) / max(p['iqr'], 1e-6)
        deviations.append(dict(feature=col, value=v, train_median=p['median'], iqr_scaled_deviation=z))
    return dict(
        method='isolation_forest_v1',
        score=value,
        threshold=threshold,
        is_anomaly=value >= threshold,
        cutoff=(x.index[-1] + pd.Timedelta(hours=1)).isoformat(),
        model_sha256=meta['model_sha256'],
        largest_feature_deviations=sorted(
            deviations, key=lambda d: abs(d['iqr_scaled_deviation']), reverse=True
        )[:3],
        explanation='Feature deviations describe context, not causal attribution of the forest score.',
        limitations='Unsupervised market unusualness, not a crash probability. No labeled anomaly accuracy is claimed.',
    )


def population_shift(current, profile):
    if current.empty or not np.isfinite(current[FEATURES].to_numpy()).all():
        raise ValueError('Drift requires nonempty finite feature rows')
    result = []
    for col in FEATURES:
        p = profile[col]
        edges = np.array([-np.inf, *p['inner_edges'], np.inf])
        counts = np.histogram(current[col].to_numpy(), bins=edges)[0]
        actual = np.maximum(counts / counts.sum(), 1e-6)
        reference = np.maximum(np.asarray(p['bin_fractions']), 1e-6)
        psi = float(np.sum((actual - reference) * np.log(actual / reference)))
        result.append(dict(feature=col, psi=psi, heuristic_drift_flag=psi >= 0.25))
    return sorted(result, key=lambda r: r['psi'], reverse=True)
