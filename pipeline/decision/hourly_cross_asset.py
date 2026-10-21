"""A fixed BTC/ETH matched retrospective experiment with an explicit execution mode."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
from urllib.request import urlopen
from uuid import uuid4

import numpy as np
import pandas as pd

from pipeline.batch.binance_archive_format import parse_kline_csv, read_zip_csv
from pipeline.decision.hourly_engineering import feature_sets
from pipeline.decision.hourly_features import prepare_grid
from pipeline.decision.hourly_future import canonical, digest, lock, seal, unseal, versions

EXTRA_COLUMNS = ['eth_log_return_1', 'eth_momentum_6', 'eth_momentum_24', 'eth_momentum_168',
                 'eth_return_std_24', 'btc_eth_return_spread_1', 'btc_eth_corr_168']


def build_cross_inputs(btc, eth):
    """Both assets must have 169 closed contiguous candles; never fill a missing ETH hour."""
    _, b, bv = prepare_grid(btc)
    _, e, ev = prepare_grid(eth.drop(columns=['symbol'], errors='ignore'))
    e = e.reindex(b.index)
    ev = ev.reindex(b.index, fill_value=False)
    br = np.log(b.close_price/b.close_price.shift(1))
    er = np.log(e.close_price/e.close_price.shift(1))
    result = pd.DataFrame(index=b.index)
    result['eth_log_return_1'] = er
    for window in (6, 24, 168):
        result[f'eth_momentum_{window}'] = np.log(e.close_price/e.close_price.shift(window))
    result['eth_return_std_24'] = er.rolling(24, min_periods=24).std(ddof=0)
    result['btc_eth_return_spread_1'] = br-er
    corr = br.rolling(168, min_periods=168).corr(er)
    # An observed constant-return window has no measurable correlation: fixed neutral 0.
    constant = br.rolling(168, min_periods=168).std(ddof=0).eq(0) | er.rolling(168, min_periods=168).std(ddof=0).eq(0)
    result['btc_eth_corr_168'] = corr.where(~constant, 0)
    full = bv.rolling(169, min_periods=169).sum().eq(169) & ev.rolling(169, min_periods=169).sum().eq(169)
    return result[EXTRA_COLUMNS].replace([np.inf, -np.inf], np.nan).where(full)


def initialize(source, future_study, root, *, offline=False):
    source, root = (Path(p).resolve() for p in (source, root))
    future_study = Path(future_study).resolve() if future_study is not None else None
    if not offline and future_study is None:
        raise ValueError('A future study is required unless offline execution is explicitly chosen')
    future_plan = unseal(future_study/'plan.json') if not offline else None
    recipe = json.loads((source/'selected_recipe.json').read_text())
    snapshot = source/'development_snapshot.csv'
    source_plan = json.loads((source/'plan.json').read_text())
    if digest(snapshot.read_bytes()) != source_plan['snapshot_sha256']:
        raise ValueError('Source development snapshot hash mismatch')
    if future_plan is not None and recipe['model_sha256'] != future_plan['model_sha256']:
        raise ValueError('Use the same frozen reference recipe as the future study')
    if digest((source/'selected_model.ubj').read_bytes()) != recipe['model_sha256']:
        raise ValueError('Source model hash mismatch')
    output = root/str(uuid4())
    output.mkdir(parents=True, exist_ok=False)
    project = Path(__file__).resolve().parents[2]
    shutil.copytree(project/'pipeline', output/'frozen/pipeline', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (output/'frozen/scripts').mkdir()
    (output/'frozen/scripts/__init__.py').touch()
    shutil.copy2(project/'scripts/hourly_cross_asset.py', output/'frozen/scripts/hourly_cross_asset.py')
    shutil.copy2(snapshot, output/'btc_development_snapshot.csv')
    params = copy.deepcopy(recipe['params'])
    params.pop('early_stopping_rounds', None)
    params['n_estimators'] = recipe['best_trees']
    folds = []
    for quarter in range(1, 5):
        start = pd.Timestamp(year=2025, month=3*(quarter-1)+1, day=1, tz='UTC')
        folds.append(dict(name=f'2025-Q{quarter}', train_start=(start-pd.DateOffset(years=1)).isoformat(),
                          validation_start=start.isoformat(), validation_end=(start+pd.DateOffset(months=3)).isoformat()))
    assets = {str(p.relative_to(output)): digest(p.read_bytes()) for p in (output/'frozen').rglob('*') if p.is_file()}
    assets['btc_development_snapshot.csv'] = digest((output/'btc_development_snapshot.csv').read_bytes())
    plan = dict(protocol='btc-eth-matched-v2', created_at=datetime.now(timezone.utc).isoformat(),
        execution_mode='offline_retrospective' if offline else 'after_prospective',
        future_study=str(future_study) if future_study is not None else None,
        future_plan_sha256=digest((future_study/'plan.json').read_bytes()) if future_plan is not None else None,
        gate='Immediate one-shot offline run; no scheduler or prospective requirement' if offline else
             'Do not fetch ETH or fit until the frozen future study has a final_score.json after its end',
        source_run=str(source), params=params, feature_sets=['compact_58', 'compact_58_plus_eth_7'],
        base_feature_names=source_plan['feature_names']['compact'],
        extra_columns=EXTRA_COLUMNS, folds=folds, target='BTC next-hour log-return in bps for fit, raw for metrics',
        metric='Pooled paired Relative MAE vs zero-return, plus all four quarter results',
        minimum_paired_coverage_per_quarter=.99, minimum_train_rows=1000,
        eth_months=pd.period_range('2023-12', '2025-12', freq='M').astype(str).tolist(),
        eth_base_url='https://data.binance.vision/data/spot/monthly/klines/ETHUSDT/1h/',
        train_policy='Rolling calendar 12 months, refit once at each quarter start; fixed 201 trees, no early stopping',
        selection_policy='Exactly two arms and four folds; no search, retuning or promotion from these results',
        limitation='2025 and the reference recipe were already used for selection; chronological replay is not unseen evaluation',
        test_2026_rows_used=0, live_promotion=False, assets=assets, versions=versions(), python_version=sys.version)
    seal(output/'plan.json', plan)
    for relative in assets:
        (output/relative).chmod(0o444)
    return output


def verify(output):
    output = Path(output)
    plan = unseal(output/'plan.json')
    for relative, expected in plan['assets'].items():
        if digest((output/relative).read_bytes()) != expected:
            raise ValueError(f'Frozen cross-asset asset changed: {relative}')
    if versions() != plan['versions'] or sys.version != plan['python_version']:
        raise ValueError('Frozen cross-asset runtime changed')
    return plan


def gate_open(plan):
    if plan.get('execution_mode') == 'offline_retrospective':
        return True
    future = Path(plan['future_study'])
    if digest((future/'plan.json').read_bytes()) != plan['future_plan_sha256']:
        raise ValueError('Future preregistration changed')
    if not (future/'final_score.json').exists():
        return False
    final = unseal(future/'final_score.json')
    future_plan = unseal(future/'plan.json')
    if final['scored_server_ms'] < future_plan['end_ms']+60_000:
        raise ValueError('Premature future result')
    return True


def read_eth(plan, output):
    cache = Path(output)/'eth_archives'
    cache.mkdir(exist_ok=True)
    def month_data(month):
        filename = f'ETHUSDT-1h-{month}.zip'
        url = plan['eth_base_url']+filename
        path = cache/filename
        check_path = cache/(filename+'.CHECKSUM')
        if not check_path.exists():
            with urlopen(url+'.CHECKSUM', timeout=30) as response:
                data = response.read()
            with check_path.open('xb') as stream:
                stream.write(data)
        expected = check_path.read_text().split()[0]
        if not path.exists():
            with urlopen(url, timeout=30) as response:
                content = response.read()
            if digest(content) != expected:
                raise ValueError(f'ETH download checksum mismatch: {month}')
            with path.open('xb') as stream:
                stream.write(content)
        if digest(path.read_bytes()) != expected:
            raise ValueError(f'ETH cache checksum mismatch: {month}')
        frame = pd.DataFrame(parse_kline_csv(read_zip_csv(path)))
        frame['open_time'] = pd.to_datetime(frame.open_time, utc=True)
        if not frame.open_time.dt.strftime('%Y-%m').eq(month).all():
            raise ValueError('ETH archive includes an unexpected month')
        return frame, dict(url=url, sha256=expected, checksum_url=url+'.CHECKSUM')
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(month_data, plan['eth_months']))
    frame = pd.concat([r[0] for r in results], ignore_index=True)
    if frame.open_time.duplicated().any() or frame.open_time.ge(pd.Timestamp('2026-01-01', tz='UTC')).any():
        raise ValueError('Duplicate or test ETH candle')
    manifest = [r[1] for r in results]
    if not (Path(output)/'source_manifest.json').exists():
        seal(Path(output)/'source_manifest.json', manifest)
    elif unseal(Path(output)/'source_manifest.json') != manifest:
        raise ValueError('Archive manifest changed')
    return frame


def metrics(y, p):
    error, baseline = np.abs(y-p).sum(), np.abs(y).sum()
    return dict(n=len(y), absolute_error_sum=float(error), zero_error_sum=float(baseline),
                mae=float(error/len(y)), zero_mae=float(baseline/len(y)), relative_mae=float(error/baseline))


def execute(output):
    from xgboost import XGBRegressor
    output = Path(output)
    with lock(output):
        plan = verify(output)
        if (output/'report.json').exists():
            return unseal(output/'report.json')
        if not gate_open(plan):
            return dict(status='waiting_for_prospective_completion', future_study=plan['future_study'])
        btc = pd.read_csv(output/'btc_development_snapshot.csv', float_precision='round_trip')
        btc['open_time'] = pd.to_datetime(btc.open_time, utc=True)
        if btc.open_time.ge(pd.Timestamp('2026-01-01', tz='UTC')).any():
            raise ValueError('Test BTC candle forbidden')
        eth = read_eth(plan, output)
        sets, meta, _ = feature_sets(btc)
        if list(sets['compact'].columns) != plan['base_feature_names'] or len(plan['base_feature_names']) != 58:
            raise ValueError('Frozen base feature schema mismatch')
        extra = build_cross_inputs(btc, eth)
        cutoff = pd.Timestamp('2025-06-01', tz='UTC')
        pd.testing.assert_frame_equal(extra.loc[:cutoff],
            build_cross_inputs(btc[btc.open_time.le(cutoff)], eth[eth.open_time.le(cutoff)]))
        btc_context = btc[btc.open_time.le(cutoff)].tail(169)
        eth_context = eth[eth.open_time.le(cutoff)].tail(169)
        pd.testing.assert_series_equal(extra.loc[cutoff], build_cross_inputs(btc_context, eth_context).loc[cutoff])
        extra = extra.reindex(meta.index)
        paired = extra.notna().all(axis=1)
        all_rows = []
        # New attempt folder permits recovery from a failed process without replacing old predictions.
        attempt = output/'attempts'/str(uuid4())
        attempt.mkdir(parents=True, exist_ok=False)
        model_hashes = {}
        arms = {'btc_only': sets['compact'], 'btc_eth': pd.concat([sets['compact'], extra], axis=1)}
        for fold in plan['folds']:
            start, end, train_start = (pd.Timestamp(fold[k]) for k in ('validation_start', 'validation_end', 'train_start'))
            eligible_val = meta.target_open_time.ge(start) & meta.target_open_time.lt(end)
            val = eligible_val & paired
            train = meta.target_open_time.ge(train_start) & meta.target_open_time.lt(start) & paired
            coverage = int(val.sum())/int(eligible_val.sum())
            if coverage < plan['minimum_paired_coverage_per_quarter'] or train.sum() < plan['minimum_train_rows']:
                raise ValueError(f'Insufficient paired coverage for {fold["name"]}; do not change the plan')
            if meta.loc[train, 'target_close_time'].max() > meta.loc[val, 'cutoff_time'].min():
                raise ValueError('Training label crosses decision cutoff')
            y = meta.loc[val, 'actual_log_return'].to_numpy()
            for name, features in arms.items():
                folder = attempt/fold['name']/name
                folder.mkdir(parents=True)
                model = XGBRegressor(**plan['params'])
                model.fit(features.loc[train], meta.loc[train, 'actual_log_return']*10000, verbose=False)
                model.save_model(folder/'model.ubj')
                predicted = model.predict(features.loc[val]).astype(float)/10000
                reload = XGBRegressor()
                reload.load_model(folder/'model.ubj')
                np.testing.assert_array_equal(model.predict(features.loc[val]), reload.predict(features.loc[val]))
                predictions = meta.loc[val].copy()
                predictions['predicted_log_return'] = predicted
                predictions.to_csv(folder/'predictions.csv', index=False, float_format='%.17g')
                seal(folder/'schema.json', list(features.columns))
                model_hashes[str(folder.relative_to(output))] = digest((folder/'model.ubj').read_bytes())
                all_rows.append(dict(fold=fold['name'], model=name, train_n=int(train.sum()),
                                     eligible_n=int(eligible_val.sum()), paired_coverage=coverage, **metrics(y, predicted)))
        pooled = {}
        for name in arms:
            rows = [r for r in all_rows if r['model'] == name]
            n = sum(r['n'] for r in rows)
            error, baseline = (sum(r[k] for r in rows) for k in ('absolute_error_sum', 'zero_error_sum'))
            pooled[name] = dict(n=n, mae=error/n, zero_mae=baseline/n, relative_mae=error/baseline)
        report = dict(status='completed', interpretation=plan['limitation'], folds=all_rows, pooled=pooled,
                      attempt=str(attempt.relative_to(output)), model_hashes=model_hashes,
                      execution_mode=plan.get('execution_mode', 'after_prospective'),
                      future_gate_completed=plan.get('execution_mode') != 'offline_retrospective',
                      causal_prefix_verified=True, context_169_verified=True,
                      reload_verified=True, test_2026_rows_used=0, live_promotion=False)
        seal(output/'report.json', report)
        return report
