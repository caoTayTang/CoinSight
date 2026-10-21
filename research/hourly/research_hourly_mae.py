"""Bounded offline research toward Relative MAE <= .97, never changes target or test."""
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import shutil
import time
from uuid import uuid4

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import HuberRegressor, QuantileRegressor, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from pipeline.batch.binance_archive_format import parse_kline_csv, read_zip_csv
from pipeline.decision.hourly_cross_asset import build_cross_inputs
from pipeline.decision.hourly_engineering import feature_sets
from pipeline.decision.hourly_future import digest, seal, unseal
from pipeline.decision.hourly_intrahour import load_intrahour
from pipeline.decision.hourly_tuning import development_splits


def recipes():
    return [dict(name='linear_median_005', family='quantile', alpha=.05),
            dict(name='linear_median_05', family='quantile', alpha=.5),
            dict(name='huber', family='huber', alpha=10., epsilon=1.1),
            dict(name='ridge_clipped', family='ridge', alpha=100., target_clip_bps=50.),
            dict(name='hist_median', family='hist', max_iter=300, max_leaf_nodes=7, min_samples_leaf=200,
                 learning_rate=.03, l2_regularization=10.),
            dict(name='cat_mae_d4', family='cat', loss_function='MAE', iterations=600, depth=4,
                 learning_rate=.03, l2_leaf_reg=20.),
            dict(name='cat_median_d6', family='cat', loss_function='Quantile:alpha=0.5', iterations=600,
                 depth=6, learning_rate=.025, l2_leaf_reg=50.),
            dict(name='xgb_mae_d2', family='xgb', n_estimators=400, max_depth=2, learning_rate=.02,
                 min_child_weight=100, reg_alpha=10., reg_lambda=10., gamma=1.)]


def make_model(recipe):
    params = {k:v for k,v in recipe.items() if k not in ('name', 'family', 'target_clip_bps')}
    family = recipe['family']
    if family == 'quantile':
        return make_pipeline(StandardScaler(), QuantileRegressor(quantile=.5, solver='highs', **params))
    if family == 'huber':
        return make_pipeline(StandardScaler(), HuberRegressor(max_iter=2000, **params))
    if family == 'ridge':
        return make_pipeline(StandardScaler(), Ridge(**params))
    if family == 'hist':
        return HistGradientBoostingRegressor(loss='absolute_error', early_stopping=False, random_state=42, **params)
    if family == 'cat':
        from catboost import CatBoostRegressor
        return CatBoostRegressor(random_seed=42, thread_count=2, verbose=False, allow_writing_files=False, **params)
    from xgboost import XGBRegressor
    return XGBRegressor(objective='reg:absoluteerror', tree_method='hist', random_state=42, n_jobs=2, **params)


def metric(y, pred):
    if not np.isfinite(pred).all():
        raise ValueError('Non-finite prediction')
    mae, zero = np.mean(np.abs(y-pred)), np.mean(np.abs(y))
    return dict(n=len(y), mae=float(mae), zero_mae=float(zero), relative_mae=float(mae/zero))


def run(source, cross_source, root, intrahour):
    source, cross_source, root = (Path(p).resolve() for p in (source, cross_source, root))
    output = root/str(uuid4())
    output.mkdir(parents=True, exist_ok=False)
    source_plan = json.loads((source/'plan.json').read_text())
    snapshot = source/'development_snapshot.csv'
    if digest(snapshot.read_bytes()) != source_plan['snapshot_sha256']:
        raise ValueError('Snapshot hash mismatch')
    plan = dict(created_at=datetime.now(timezone.utc).isoformat(), objective_relative_mae=.97,
        target='BTCUSDT next-hour log-return; all original validation hours; zero-return baseline',
        train='2024 target open times only', diagnostic='Jan-Jun 2025', selection='Jul-Dec 2025',
        recipes=recipes(), sets=['compact', 'eth']+(['intrahour'] if intrahour else []),
        prediction_multipliers=[1., .5], target_units='bps fit; raw log-return evaluation',
        early_stopping=False, test_2026_rows_used=0, live_promotion=False, scheduler=False,
        source_snapshot_sha256=digest(snapshot.read_bytes()), source_run=str(source), cross_source=str(cross_source),
        versions={p:importlib.metadata.version(p) for p in ['numpy','pandas','scikit-learn','xgboost','catboost']},
        caveat='Reused validation; expanded search budget; not unseen evidence')
    seal(output/'plan.json', plan)
    project=Path(__file__).resolve().parents[2]
    shutil.copytree(project/'pipeline', output/'code/pipeline', ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copy2(Path(__file__), output/'code/research_hourly_mae.py')
    shutil.copy2(snapshot, output/'development_snapshot.csv')
    print(f'RUN={output}', flush=True)
    btc=pd.read_csv(snapshot, float_precision='round_trip')
    btc['open_time']=pd.to_datetime(btc.open_time,utc=True)
    if btc.open_time.ge(pd.Timestamp('2026-01-01',tz='UTC')).any():
        raise ValueError('Test candles forbidden')
    eth_frames=[]
    for item in unseal(cross_source/'source_manifest.json'):
        path=cross_source/'eth_archives'/item['url'].rsplit('/',1)[-1]
        if digest(path.read_bytes())!=item['sha256']:
            raise ValueError('ETH source hash mismatch')
        eth_frames.append(pd.DataFrame(parse_kline_csv(read_zip_csv(path))))
    eth=pd.concat(eth_frames,ignore_index=True)
    eth['open_time']=pd.to_datetime(eth.open_time,utc=True)
    seal(output/'eth_sources.json',unseal(cross_source/'source_manifest.json'))
    sets,meta,_=feature_sets(btc)
    cross=build_cross_inputs(btc,eth).reindex(meta.index)
    features={'compact':sets['compact'], 'eth':pd.concat([sets['compact'],cross],axis=1)}
    if intrahour:
        print('Downloading/checking 25 BTC 5m archives and building within-hour features',flush=True)
        intra=load_intrahour(output,btc).reindex(meta.index)
        features['intrahour']=pd.concat([features['eth'],intra],axis=1)
    masks=development_splits(meta)
    val=masks['early_stop']|masks['selection']
    train=masks['train'] & meta.target_open_time.ge(pd.Timestamp('2024-01-01',tz='UTC'))
    # Every arm must use identical original validation hours, with no favorable filtering.
    usable=pd.Series(True,index=meta.index)
    for frame in features.values():
        if frame.loc[val].isna().any().any():
            raise ValueError('New source missing original validation samples; cannot drop target hours')
        usable &= frame.notna().all(axis=1)
    train &= usable
    if train.sum()<8000 or val.sum()!=8760 or masks['selection'].sum()!=4416:
        raise ValueError('Unexpected common train/validation sample count')
    y=meta.actual_log_return*10000
    rows=[]
    with threadpool_limits(limits=2):
        for set_name, frame in features.items():
            for recipe in plan['recipes']:
                name=set_name+'__'+recipe['name']
                folder=output/name
                folder.mkdir()
                started=time.monotonic()
                print(f'Fitting {name}: {int(train.sum())} train, {frame.shape[1]} features',flush=True)
                model=make_model(recipe)
                target=y.loc[train].to_numpy()
                if 'target_clip_bps' in recipe:
                    target=np.clip(target,-recipe['target_clip_bps'],recipe['target_clip_bps'])
                model.fit(frame.loc[train],target)
                pred=model.predict(frame.loc[val])/10000
                joblib.dump(model,folder/'model.joblib')
                np.testing.assert_array_equal(pred,joblib.load(folder/'model.joblib').predict(frame.loc[val])/10000)
                saved=meta.loc[val].copy()
                saved['partition']=np.where(masks['early_stop'].loc[val],'early_stop','selection')
                saved['predicted_log_return']=pred
                saved.to_csv(folder/'predictions.csv',index=False,float_format='%.17g')
                seal(folder/'schema.json',list(frame.columns))
                for multiplier in plan['prediction_multipliers']:
                    metrics={}
                    for partition in ['early_stop','selection']:
                        selected=saved.partition.eq(partition)
                        metrics[partition]=metric(saved.loc[selected,'actual_log_return'].to_numpy(),pred[selected]*multiplier)
                    row=dict(name=name,multiplier=multiplier,feature_set=set_name,recipe=recipe,
                        train_n=int(train.sum()),n_features=frame.shape[1],metrics=metrics,
                        model_sha256=digest((folder/'model.joblib').read_bytes()),elapsed_seconds=time.monotonic()-started)
                    rows.append(row)
                    print(f'  shrink={multiplier}: selection Relative MAE={metrics["selection"]["relative_mae"]:.6f}',flush=True)
                seal(folder/'metrics.json',rows[-2:])
    winner=min(rows,key=lambda r:r['metrics']['selection']['relative_mae'])
    seal(output/'report.json',dict(plan_sha256=digest((output/'plan.json').read_bytes()),rows=rows,winner=winner,
        target_met=winner['metrics']['selection']['relative_mae']<=.97,validation_rows_per_candidate=8760,
        test_2026_rows_used=0,reload_verified=True,train_scalers_fit_on_train_only=True))
    print('WINNER '+json.dumps(winner),flush=True)
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--cross-source',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,default=Path('data/models/hourly-mae-research'))
    parser.add_argument('--intrahour',action='store_true')
    args=parser.parse_args()
    run(args.source,args.cross_source,args.output_root,args.intrahour)
