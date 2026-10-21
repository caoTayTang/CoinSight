"""Describe frozen validation stability and one fixed taker-buy ablation; no search."""
import argparse
import copy
import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
from uuid import uuid4
import zipfile
from urllib.request import urlopen

import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from pipeline.decision.hourly_engineering import feature_sets
from pipeline.decision.hourly_model import sha256, write_json
from pipeline.decision.hourly_tuning import development_splits


def stability(frame):
    """Ratios are computed from pooled errors, never averaged across months."""
    rows = []
    times = pd.to_datetime(frame.target_open_time, utc=True)
    groups = [('month', times.dt.strftime('%Y-%m')), ('quarter', times.dt.strftime('%Y-Q') + times.dt.quarter.astype(str)),
              ('partition', frame.partition)]
    for period, labels in groups:
        for label, group in frame.groupby(labels):
            y, p = group.actual_log_return.to_numpy(), group.predicted_log_return.to_numpy()
            baseline, error = np.abs(y).mean(), np.abs(y-p).mean()
            rows.append(dict(period=period, label=label, n=len(group), mae=error,
                             zero_mae=baseline, relative_mae=error/baseline,
                             improvement_pct=100*(1-error/baseline),
                             direction_pct=100*np.mean(np.sign(y)==np.sign(p)),
                             target_std=np.std(y), prediction_std=np.std(p)))
    return pd.DataFrame(rows)


def taker_features(raw):
    """Only closed candles; a full 169-candle context is sufficient."""
    grid = raw.set_index('open_time').sort_index().asfreq('h')
    buy, total = grid.taker_buy_quote, grid.volume_quote
    result = pd.DataFrame(index=grid.index)
    for window in (1, 6, 24, 168):
        b = buy.rolling(window, min_periods=window).sum()
        v = total.rolling(window, min_periods=window).sum()
        # Neutral imbalance for an observed zero-volume window, never fill gaps.
        result[f'taker_quote_imbalance_{window}'] = (2*b/v.where(v.ne(0))-1).where(v.ne(0), 0).where(v.notna())
    return result


def read_taker(snapshot, root):
    """Read only needed monthly archives, check checksum and exact candle identity."""
    frames, manifest = [], []
    for month in sorted(snapshot.open_time.dt.strftime('%Y-%m').unique()):
        path = root / f'BTCUSDT-1h-{month}.zip'
        digest = sha256(path)
        known = snapshot.loc[snapshot.source_file.eq(path.name), 'sha256'].dropna().unique()
        if len(known) > 1:
            raise ValueError('Conflicting snapshot archive hashes')
        checksum_source = 'frozen snapshot lineage'
        if len(known):
            expected = known[0]
        else:
            checksum_source = f'https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/{path.name}.CHECKSUM'
            with urlopen(checksum_source, timeout=30) as response:
                expected = response.read().decode().split()[0]
        if expected != digest:
            raise ValueError(f'Archive checksum mismatch: {path}')
        manifest.append(dict(path=str(path), sha256=digest, checksum_source=checksum_source))
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if n.endswith('.csv')]
            if len(names) != 1:
                raise ValueError('Expected one CSV')
            rows = list(csv.reader(io.StringIO(archive.read(names[0]).decode())))
        for row in rows:
            if not row or not row[0].isdigit():
                continue
            if len(row) != 12:
                raise ValueError('Expected full 12-column kline')
            stamp = int(row[0])
            frames.append([pd.to_datetime(stamp, unit='us' if stamp >= 10**14 else 'ms', utc=True),
                           *map(float, row[1:6]), float(row[7]), float(row[8]), float(row[9]), float(row[10])])
    raw = pd.DataFrame(frames, columns=['open_time', 'open_price', 'high_price', 'low_price', 'close_price',
                                      'volume_base', 'volume_quote', 'trade_count', 'taker_buy_base', 'taker_buy_quote'])
    if raw.open_time.duplicated().any() or (raw.open_time >= pd.Timestamp('2026-01-01', tz='UTC')).any():
        raise ValueError('Duplicate or test candle')
    joined = snapshot.merge(raw, on='open_time', suffixes=('_snapshot', ''), validate='one_to_one', how='left')
    for column in ['open_price', 'high_price', 'low_price', 'close_price', 'volume_quote', 'trade_count']:
        # Warehouse quote volume is NUMERIC(..., 2); archive keeps more decimals.
        tolerance = .005001 if column == 'volume_quote' else 1e-8
        np.testing.assert_allclose(joined[column], joined[column+'_snapshot'], rtol=1e-12, atol=tolerance)
    for buy, total in [('taker_buy_base', 'volume_base'), ('taker_buy_quote', 'volume_quote')]:
        if not np.isfinite(joined[buy]).all() or (joined[buy] < 0).any() or (joined[buy] > joined[total]+1e-8).any():
            raise ValueError('Invalid taker volume')
    return joined[raw.columns], manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--archive-root', type=Path, default=Path('data/raw/binance/BTCUSDT/1h'))
    parser.add_argument('--output-root', type=Path, default=Path('data/models/hourly-diagnostics'))
    args = parser.parse_args()
    source = args.run_dir
    recipe = json.loads((source/'selected_recipe.json').read_text())
    snapshot_path = source/'development_snapshot.csv'
    if sha256(snapshot_path) != json.loads((source/'plan.json').read_text())['snapshot_sha256']:
        raise ValueError('Snapshot hash mismatch')
    if sha256(source/'selected_model.ubj') != recipe['model_sha256']:
        raise ValueError('Selected model hash mismatch')
    snapshot = pd.read_csv(snapshot_path, float_precision='round_trip')
    snapshot['open_time'] = pd.to_datetime(snapshot.open_time, utc=True)
    if (snapshot.open_time >= pd.Timestamp('2026-01-01', tz='UTC')).any():
        raise ValueError('Test candles forbidden')
    saved_path = source/recipe['name']/'validation_predictions.csv'
    saved = pd.read_csv(saved_path, float_precision='round_trip')
    times = pd.to_datetime(saved.target_open_time, utc=True)
    if times.duplicated().any() or not times.is_monotonic_increasing or not times.between(
            pd.Timestamp('2025-01-01', tz='UTC'), pd.Timestamp('2026-01-01', tz='UTC'), inclusive='left').all():
        raise ValueError('Invalid validation timestamps')
    output = args.output_root/str(uuid4())
    output.mkdir(parents=True, exist_ok=False)
    params = copy.deepcopy(recipe['params'])
    params.pop('early_stopping_rounds', None)
    params['n_estimators'] = recipe['best_trees']
    plan = dict(created_at=datetime.now(timezone.utc).isoformat(), source_run=str(source),
                snapshot_sha256=sha256(snapshot_path), predictions_sha256=sha256(saved_path), recipe=recipe,
                experiment='One matched pair; compact vs compact + four quote taker imbalances',
                params=params, train_start=recipe['train_start'], target='next-hour log-return * 10000',
                windows=[1, 6, 24, 168], test_rows_used=0, search=False, live_promotion=False,
                interpretation='Descriptive reused-2025 validation; not unseen evidence; no winner promotion',
                source_documentation='https://github.com/binance/binance-public-data/#klines')
    write_json(output/'plan.json', plan)  # Before reading new feature results or fitting.
    stability(saved).to_csv(output/'selected_stability.csv', index=False)
    raw, manifest = read_taker(snapshot, args.archive_root)
    write_json(output/'source_manifest.json', manifest)
    raw.to_csv(output/'taker_snapshot.csv', index=False, float_format='%.17g')
    sets, meta, _ = feature_sets(snapshot)
    masks = development_splits(meta)
    extra = taker_features(raw).reindex(meta.input_open_time)
    extra.index = meta.index
    if extra.isna().any().any():
        raise ValueError('Taker features must preserve every original sample')
    # Temporal invariance and bounded context checks before fit.
    cutoff = meta.input_open_time.iloc[len(meta)//2]
    prefix = raw[raw.open_time <= cutoff]
    pd.testing.assert_frame_equal(taker_features(raw).loc[:cutoff], taker_features(prefix))
    pd.testing.assert_series_equal(taker_features(prefix).iloc[-1], taker_features(prefix.tail(169)).iloc[-1])
    train = masks['train'] & meta.target_open_time.ge(pd.Timestamp(recipe['train_start'], tz='UTC'))
    val = masks['early_stop'] | masks['selection']
    np.testing.assert_array_equal(pd.to_datetime(saved.target_open_time, utc=True), meta.loc[val, 'target_open_time'])
    np.testing.assert_array_equal(saved.actual_log_return, meta.loc[val, 'actual_log_return'])
    results = []
    for name, features in [('compact', sets['compact']), ('compact_taker', pd.concat([sets['compact'], extra], axis=1))]:
        model = XGBRegressor(**params)
        model.fit(features.loc[train], meta.loc[train, 'actual_log_return']*10000, verbose=False)
        model.save_model(output/f'{name}.ubj')
        predictions = meta.loc[val].copy()
        predictions['partition'] = np.where(masks['early_stop'].loc[val], 'early_stop', 'selection')
        predictions['predicted_log_return'] = model.predict(features.loc[val]).astype(float)/10000
        replay = XGBRegressor()
        replay.load_model(output/f'{name}.ubj')
        np.testing.assert_array_equal(model.predict(features.loc[val]), replay.predict(features.loc[val]))
        predictions.to_csv(output/f'{name}_predictions.csv', index=False, float_format='%.17g')
        write_json(output/f'{name}_features.json', list(features.columns))
        summary = stability(predictions)
        summary.insert(0, 'model', name)
        results.append(summary)
        if name == 'compact':
            # Same tree budget/data/seed must reproduce the frozen winner.
            np.testing.assert_allclose(predictions.predicted_log_return, saved.predicted_log_return, rtol=1e-6, atol=1e-10)
    pd.concat(results, ignore_index=True).to_csv(output/'ablation_stability.csv', index=False)
    write_json(output/'checks.json', dict(archive_hashes_verified=len(manifest), snapshot_candles_matched=len(raw),
               causal_prefix_verified=True, context_169_verified=True, baseline_reproduced=True,
               model_reload_verified=True, test_rows_used=0, taker_snapshot_sha256=sha256(output/'taker_snapshot.csv'),
               source_code_sha256=sha256(Path(__file__))))
    (output/'diagnose_hourly_signal.py').write_bytes(Path(__file__).read_bytes())
    print(output)
    print(pd.concat(results).query("period == 'partition'").to_string(index=False))


if __name__ == '__main__':
    main()
