"""Matched fixed-family research using genuinely new futures and settled funding data."""
import argparse
from datetime import datetime,timezone
from pathlib import Path
import shutil
from uuid import uuid4

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from pipeline.batch.binance_archive_format import parse_kline_csv,read_zip_csv
from pipeline.decision.hourly_cross_asset import build_cross_inputs
from pipeline.decision.hourly_derivatives import build_derivatives,load_derivatives
from pipeline.decision.hourly_engineering import feature_sets
from pipeline.decision.hourly_future import digest,seal,unseal
from pipeline.decision.hourly_tuning import development_splits
from research.hourly.research_hourly_mae import make_model,metric,recipes


def run(source,root):
    source,root=Path(source).resolve(),Path(root).resolve()
    original=unseal(source/'plan.json')
    snapshot=source/'development_snapshot.csv'
    if digest(snapshot.read_bytes())!=original['source_snapshot_sha256']:
        raise ValueError('Source snapshot changed')
    output=root/str(uuid4())
    output.mkdir(parents=True,exist_ok=False)
    models=[r for r in recipes() if r['family'] in ('hist','cat','xgb')]
    models.append(dict(name='linear_median_0005',family='quantile',alpha=.005))
    plan=dict(created_at=datetime.now(timezone.utc).isoformat(),source=str(source),goal_relative_mae=.97,
        source_plan_sha256=digest((source/'plan.json').read_bytes()),recipes=models,
        sets=['eth','derivatives','derivatives_intrahour'],train='2024',diagnostic='Jan-Jun 2025',selection='Jul-Dec 2025',
        multipliers=[1.,.5],funding_delay='Use only funding calc_time <= input open, >=1h before prediction cutoff',
        basis='Closed futures candle vs same-hour closed spot candle; rolling 24h statistics',
        missing_policy='Require every original 8760 validation hour; do not drop missing-source targets',
        source_snapshot_sha256=digest(snapshot.read_bytes()),test_2026_rows_used=0,scheduler=False,live_promotion=False,
        caveat='Reused validation; additional selection budget; archive is not proven point-in-time')
    seal(output/'plan.json',plan)
    shutil.copy2(Path(__file__),output/'research_hourly_derivatives.py')
    shutil.copy2(Path(__file__).resolve().parents[2]/'pipeline/decision/hourly_derivatives.py',output/'hourly_derivatives.py')
    print(f'RUN={output}',flush=True)
    btc=pd.read_csv(snapshot,float_precision='round_trip')
    btc['open_time']=pd.to_datetime(btc.open_time,utc=True)
    if btc.open_time.ge(pd.Timestamp('2026-01-01',tz='UTC')).any():
        raise ValueError('Test candles forbidden')
    cross_source=Path(original['cross_source'])
    eth=[]
    for item in unseal(source/'eth_sources.json'):
        path=cross_source/'eth_archives'/item['url'].rsplit('/',1)[-1]
        if digest(path.read_bytes())!=item['sha256']:
            raise ValueError('ETH source changed')
        eth.append(pd.DataFrame(parse_kline_csv(read_zip_csv(path))))
    eth=pd.concat(eth,ignore_index=True)
    eth['open_time']=pd.to_datetime(eth.open_time,utc=True)
    base,meta,_=feature_sets(btc)
    features={'eth':pd.concat([base['compact'],build_cross_inputs(btc,eth).reindex(meta.index)],axis=1)}
    print('Downloading/verifying 50 futures/funding archives',flush=True)
    futures,funding=load_derivatives(output)
    extra=build_derivatives(btc,futures,funding)
    cutoff=pd.Timestamp('2025-06-01',tz='UTC')
    pd.testing.assert_frame_equal(extra.loc[:cutoff],build_derivatives(btc[btc.open_time.le(cutoff)],
        futures[futures.open_time.le(cutoff)],funding[funding.calc_time.le(cutoff)]))
    extra.to_csv(output/'derivatives_features.csv',float_format='%.17g')
    features['derivatives']=pd.concat([features['eth'],extra.reindex(meta.index)],axis=1)
    intra=pd.read_csv(source/'intrahour_features.csv',index_col=0,float_precision='round_trip')
    intra.index=pd.to_datetime(intra.index,utc=True)
    features['derivatives_intrahour']=pd.concat([features['derivatives'],intra.reindex(meta.index)],axis=1)
    masks=development_splits(meta)
    val=masks['early_stop']|masks['selection']
    train=masks['train']&meta.target_open_time.ge(pd.Timestamp('2024-01-01',tz='UTC'))
    for name,frame in features.items():
        if frame.loc[val].isna().any().any():
            print(frame.loc[val].isna().sum().to_string(),flush=True)
            raise ValueError(f'{name} lacks original validation samples')
        train &= frame.notna().all(axis=1)
    if train.sum()<8000 or val.sum()!=8760:
        raise ValueError('Unexpected sample count')
    y=meta.actual_log_return*10000
    rows=[]
    with threadpool_limits(limits=2):
        for set_name,frame in features.items():
            for recipe in models:
                name=set_name+'__'+recipe['name']
                folder=output/name
                folder.mkdir()
                print(f'Fitting {name}: {frame.shape[1]} features',flush=True)
                model=make_model(recipe)
                model.fit(frame.loc[train],y.loc[train])
                predicted=model.predict(frame.loc[val])/10000
                joblib.dump(model,folder/'model.joblib')
                np.testing.assert_array_equal(predicted,joblib.load(folder/'model.joblib').predict(frame.loc[val])/10000)
                saved=meta.loc[val].copy()
                saved['partition']=np.where(masks['early_stop'].loc[val],'early_stop','selection')
                saved['predicted_log_return']=predicted
                saved.to_csv(folder/'predictions.csv',index=False,float_format='%.17g')
                seal(folder/'schema.json',list(frame.columns))
                for multiplier in plan['multipliers']:
                    metrics={}
                    for part in ('early_stop','selection'):
                        selected=saved.partition.eq(part)
                        metrics[part]=metric(saved.loc[selected,'actual_log_return'].to_numpy(),predicted[selected]*multiplier)
                    rows.append(dict(name=name,multiplier=multiplier,metrics=metrics,train_n=int(train.sum()),
                                     model_sha256=digest((folder/'model.joblib').read_bytes())))
                    print(f'  shrink={multiplier}: Relative MAE={metrics["selection"]["relative_mae"]:.6f}',flush=True)
    winner=min(rows,key=lambda r:r['metrics']['selection']['relative_mae'])
    seal(output/'report.json',dict(rows=rows,winner=winner,target_met=winner['metrics']['selection']['relative_mae']<=.97,
                                  causal_prefix_verified=True,reload_verified=True,test_2026_rows_used=0))
    print(f'WINNER {winner}',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,default=Path('data/models/hourly-derivatives-research'))
    args=parser.parse_args()
    run(args.source,args.output_root)
