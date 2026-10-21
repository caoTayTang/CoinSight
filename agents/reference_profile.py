"""Build the forecast model's drift reference: decile bins of its input features on its training period.

  python -m agents.reference_profile --out data/models/agent-serving-bundle/v1/reference_profile.json

Reads BTC hourly candles from the warehouse (DATABASE_URL), computes features with the serving feature builder,
and records, per feature, the inner decile edges and the share of training rows per bin: the format
model_health compares the last 168 hours against with PSI (docs/model_integration.md).
"""

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from pipeline.decision.hourly_engineering import build_experimental_inputs

# The ensemble's compact member was fit from 2023 and calibrated through 2025-06 (ensemble.json).
PERIOD = ('2023-01-01', '2025-07-01')
WARMUP_HOURS = 200


def load_candles(url, start, end):
    import psycopg

    with psycopg.connect(url) as conn:
        frame = pd.read_sql(
            """select f.open_time, f.open_price, f.high_price, f.low_price, f.close_price, f.volume_quote,
                      f.trade_count
               from dw.fact_ohlcv_hourly f join dw.dim_asset a using (asset_key)
               join dw.dim_source s using (source_key)
               where a.symbol = 'BTC' and s.source_code = 'binance' and f.open_time >= %s and f.open_time < %s
               order by f.open_time""",
            conn,
            params=(start, end),
        )
    frame['open_time'] = pd.to_datetime(frame['open_time'], utc=True)
    return frame


def profile(features: pd.DataFrame, names):
    result = {}
    for name in names:
        values = features[name].to_numpy(dtype=float)
        values = values[np.isfinite(values)]
        # Unique edges: discrete features (hour of day, flags) have repeated deciles.
        edges = np.unique(np.quantile(values, np.linspace(0.1, 0.9, 9)))
        counts = np.histogram(values, bins=np.array([-np.inf, *edges, np.inf]))[0]
        result[name] = dict(inner_edges=edges.tolist(), bin_fractions=(counts / counts.sum()).tolist())
    return result


def build(url, bundle_dir):
    spec = json.loads((bundle_dir / 'ensemble.json').read_text())
    compact = next(m for m in spec['payload']['members'] if m['feature_set'] == 'compact')
    others = {f for m in spec['payload']['members'] for f in m['features']} - set(compact['features'])
    start = (pd.Timestamp(PERIOD[0], tz='UTC') - pd.Timedelta(hours=WARMUP_HOURS)).isoformat()
    candles = load_candles(url, start, PERIOD[1])
    rows = build_experimental_inputs(candles)['compact']
    rows = rows[rows.index >= pd.Timestamp(PERIOD[0], tz='UTC')] if isinstance(rows.index, pd.DatetimeIndex) else rows
    rows = rows[compact['features']].dropna()
    if len(rows) < 5000:
        raise ValueError(f'Only {len(rows)} complete feature rows; the warehouse is missing training-period history')
    return dict(
        model_id='btc_hourly_frozen_ensemble_v1',
        bundle_payload_sha256=spec['sha256'],
        feature_set='compact',
        period=dict(start=PERIOD[0], end=PERIOD[1]),
        rows=len(rows),
        features=profile(rows, compact['features']),
        # The ETH member's cross-asset features need ETH history the warehouse doesn't hold before 2026.
        not_covered=sorted(others),
        created_at=datetime.now(timezone.utc).isoformat(),
        source_sha256=hashlib.sha256(pd.util.hash_pandas_object(candles, index=False).values.tobytes()).hexdigest(),
    )


def main():
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--bundle', default='data/models/agent-serving-bundle/v1')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    url = os.getenv('DATABASE_URL', 'postgresql://crypto:crypto@localhost:5432/crypto_dw')
    result = build(url, Path(args.bundle))
    Path(args.out).write_text(json.dumps(result, indent=1))
    print(f"{result['rows']} rows, {len(result['features'])} features, {len(result['not_covered'])} not covered")


if __name__ == '__main__':
    main()
