"""One bounded offline BTC 1h experiment with lagged OI/positioning information."""
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
from pipeline.decision.hourly_engineering import feature_sets
from pipeline.decision.hourly_future import digest,seal,unseal
from pipeline.decision.hourly_positioning import build_positioning,load_positioning
from pipeline.decision.hourly_tuning import development_splits
from research.hourly.research_hourly_mae import make_model,metric,recipes


def run(source,derivatives,cache,root,delay_minutes=60):
    source,derivatives,cache,root=(Path(p).resolve() for p in (source,derivatives,cache,root))
    original=unseal(source/'plan.json')
    snapshot=source/'development_snapshot.csv'
    if digest(snapshot.read_bytes())!=original['source_snapshot_sha256']:
        raise ValueError('BTC snapshot hash mismatch')
    output=root/str(uuid4())
    output.mkdir(parents=True,exist_ok=False)
    models=[r for r in recipes() if r['family'] in ('cat','hist','xgb')]
    plan=dict(created_at=datetime.now(timezone.utc).isoformat(),source=str(source),derivatives_source=str(derivatives),
        goal_relative_mae=.97,source_snapshot_sha256=digest(snapshot.read_bytes()),
        derivatives_features_sha256=digest((derivatives/'derivatives_features.csv').read_bytes()),
        intrahour_features_sha256=digest((source/'intrahour_features.csv').read_bytes()),
        train='2024 only',diagnostic='Jan-Jun 2025',selection='Jul-Dec 2025',
        source_dates=['2023-12-30','2025-12-31'],source_cache=str(cache),
        sets=['eth','positioning','positioning_derivatives','positioning_all'],recipes=models,multipliers=[1.,.5],
        delay_minutes=delay_minutes,
        information_policy=f'Latest metrics create_time <= prediction cutoff minus {delay_minutes}min; asof tolerance 2h; no future fill',
        missing_policy='Keep all targets; native missing-value handling by tree learners; no future fill or target removal',
        no_early_stopping=True,test_2026_rows_used=0,scheduler=False,live_promotion=False,
        caveat='Reused selection, archive timestamps not independently established point-in-time availability')
    seal(output/'plan.json',plan)
    project=Path(__file__).resolve().parents[2]
    shutil.copytree(project/'pipeline',output/'code/pipeline',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copy2(Path(__file__),output/'code/research_hourly_positioning.py')
    print(f'RUN={output}',flush=True)
    raw=load_positioning(output,cache)
    btc=pd.read_csv(snapshot,float_precision='round_trip')
    btc['open_time']=pd.to_datetime(btc.open_time,utc=True)
    if btc.open_time.ge(pd.Timestamp('2026-01-01',tz='UTC')).any():
        raise ValueError('Test BTC candles forbidden')
    cross_source=Path(original['cross_source'])
    eth=[]
    for item in unseal(source/'eth_sources.json'):
        path=cross_source/'eth_archives'/item['url'].rsplit('/',1)[-1]
        if digest(path.read_bytes())!=item['sha256']:
            raise ValueError('ETH archive changed')
        eth.append(pd.DataFrame(parse_kline_csv(read_zip_csv(path))))
    eth=pd.concat(eth,ignore_index=True)
    eth['open_time']=pd.to_datetime(eth.open_time,utc=True)
    base,meta,_=feature_sets(btc)
    baseline=pd.concat([base['compact'],build_cross_inputs(btc,eth).reindex(meta.index)],axis=1)
    extra=build_positioning(btc,raw,delay_minutes)
    cutoff=pd.Timestamp('2025-06-01',tz='UTC')
    allowed=cutoff+pd.Timedelta(hours=1)-pd.Timedelta(minutes=delay_minutes)
    pd.testing.assert_frame_equal(extra.loc[:cutoff],build_positioning(btc[btc.open_time.le(cutoff)],raw[raw.create_time.le(allowed)],delay_minutes))
    extra.to_csv(output/'positioning_features.csv',float_format='%.17g')
    extra=extra.reindex(meta.index)
    derivative_features=pd.read_csv(derivatives/'derivatives_features.csv',index_col=0,float_precision='round_trip')
    derivative_features.index=pd.to_datetime(derivative_features.index,utc=True)
    intra=pd.read_csv(source/'intrahour_features.csv',index_col=0,float_precision='round_trip')
    intra.index=pd.to_datetime(intra.index,utc=True)
    features={'eth':baseline,'positioning':pd.concat([baseline,extra],axis=1)}
    features['positioning_derivatives']=pd.concat([features['positioning'],derivative_features.reindex(meta.index)],axis=1)
    features['positioning_all']=pd.concat([features['positioning_derivatives'],intra.reindex(meta.index)],axis=1)
    masks=development_splits(meta)
    train=masks['train']&meta.target_open_time.ge(pd.Timestamp('2024-01-01',tz='UTC'))
    val=masks['early_stop']|masks['selection']
    if train.sum()!=8784 or val.sum()!=8760 or masks['selection'].sum()!=4416:
        raise ValueError('Original sample counts changed')
    if baseline.loc[train|val].isna().any().any():
        raise ValueError('Baseline input incomplete')
    coverage={}
    for part,mask in [('train',train),('early_stop',masks['early_stop']),('selection',masks['selection'])]:
        coverage[part]=dict(n=int(mask.sum()),snapshot_available_pct=float(extra.loc[mask,'positioning_available'].mean()*100),
            all_positioning_features_present_pct=float(extra.loc[mask].notna().all(axis=1).mean()*100),
            missing_by_feature=extra.loc[mask].isna().sum().astype(int).to_dict())
    seal(output/'source_coverage.json',coverage)
    print('Positioning coverage:',{k:v['snapshot_available_pct'] for k,v in coverage.items()},flush=True)
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
        causal_prefix_verified=True,reload_verified=True,source_coverage=coverage,test_2026_rows_used=0))
    print(f'WINNER {winner}',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--derivatives',type=Path,required=True)
    parser.add_argument('--cache',type=Path,default=Path('data/models/hourly-positioning-sources'))
    parser.add_argument('--output-root',type=Path,default=Path('data/models/hourly-positioning-research'))
    parser.add_argument('--delay-minutes',type=int,choices=[10,60],default=60)
    args=parser.parse_args()
    run(args.source,args.derivatives,args.cache,args.output_root,args.delay_minutes)
