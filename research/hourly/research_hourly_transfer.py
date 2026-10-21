"""Auxiliary ETH training examples with causal per-asset risk normalization."""
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
from pipeline.decision.hourly_engineering import feature_sets
from pipeline.decision.hourly_future import digest,seal,unseal
from pipeline.decision.hourly_tuning import development_splits
from research.hourly.research_hourly_mae import make_model,metric,recipes


def normalized_features(frame,train):
    """Risk scaling is causal; activity level offsets are learned on train only."""
    result=frame.copy()
    scale=np.maximum(frame.return_std_24.to_numpy(),.0001)
    for name in result:
        if name in ('log_return','open_close_return','range_pct','upper_wick','lower_wick') or name.startswith(
            ('momentum_','return_std_','mean_return_','median_return_','log_distance_mean_close_','distance_high_','distance_low_')):
            result[name]=result[name].to_numpy()/scale
    offsets={}
    for name in ('log_volume','log_trade_count','log_quote_per_trade'):
        offsets[name]=float(result.loc[train,name].median())
        result[name]-=offsets[name]
    return result,scale,offsets


def run(source,history,root):
    source,history,root=(Path(p).resolve() for p in (source,history,root))
    old=unseal(source/'plan.json')
    snapshot=source/'development_snapshot.csv'
    if digest(snapshot.read_bytes())!=old['source_snapshot_sha256']:
        raise ValueError('BTC source changed')
    output=root/str(uuid4())
    output.mkdir(parents=True,exist_ok=False)
    models=[r for r in recipes() if r['family'] in ('cat','hist','xgb')]
    plan=dict(created_at=datetime.now(timezone.utc).isoformat(),source=str(source),history_source=str(history),
        goal_relative_mae=.97,source_snapshot_sha256=digest(snapshot.read_bytes()),train='2023-2024 only',
        auxiliary_asset='ETH return labels before 2025 only',selection='BTC Jul-Dec 2025, all original 4416 hours',
        pools=['btc_only','btc_eth_shared','btc_eth_indicator'],recipes=models,multipliers=[1.,.5],
        target_normalization='Past 24h return std floor 1bp; invert to raw BTC log-return for every score',
        weights='Past volatility / mean train volatility within each asset; equal weight per observed example',
        activity_normalization='Log activity offsets from each asset training samples only',
        test_2026_rows_used=0,scheduler=False,live_promotion=False,
        caveat='Additional selection on reused validation; transfer is a hypothesis, not unseen evidence')
    seal(output/'plan.json',plan)
    shutil.copy2(Path(__file__),output/'research_hourly_transfer.py')
    print(f'RUN={output}',flush=True)
    btc=pd.read_csv(snapshot,float_precision='round_trip')
    btc.open_time=pd.to_datetime(btc.open_time,utc=True)
    eth=[]
    for item in unseal(history/'eth_sources.json'):
        path=history/item['path']
        if digest(path.read_bytes())!=item['sha256']:
            raise ValueError('ETH archive changed')
        eth.append(pd.DataFrame(parse_kline_csv(read_zip_csv(path))))
    eth=pd.concat(eth,ignore_index=True)
    eth.open_time=pd.to_datetime(eth.open_time,utc=True)
    for frame in (btc,eth):
        if frame.open_time.ge(pd.Timestamp('2026-01-01',tz='UTC')).any():
            raise ValueError('Test data forbidden')
    assets={}
    for name,raw in [('btc',btc),('eth',eth)]:
        sets,meta,_=feature_sets(raw)
        train=meta.target_open_time.ge(pd.Timestamp('2023-01-01',tz='UTC'))&meta.target_open_time.lt(pd.Timestamp('2025-01-01',tz='UTC'))
        normalized,scale,offsets=normalized_features(sets['compact'],train)
        target=meta.actual_log_return.to_numpy()/scale
        weights=scale/scale[train].mean()
        assets[name]=dict(features=normalized,meta=meta,train=train.to_numpy(),scale=scale,target=target,weights=weights)
        seal(output/(name+'_normalization.json'),dict(offsets=offsets,train_n=int(train.sum()),
            last_train_label_close=meta.loc[train,'target_close_time'].max().isoformat()))
    bm=assets['btc']['meta'];masks=development_splits(bm)
    val=(masks['early_stop']|masks['selection']).to_numpy()
    if val.sum()!=8760 or masks['selection'].sum()!=4416:
        raise ValueError('Original BTC validation changed')
    rows=[]
    with threadpool_limits(limits=2):
        for pool in plan['pools']:
            x_parts=[];y_parts=[];w_parts=[]
            for name in (['btc'] if pool=='btc_only' else ['btc','eth']):
                asset=assets[name]
                frame=asset['features'].loc[asset['train']].copy()
                if pool=='btc_eth_indicator':
                    frame['asset_is_btc']=float(name=='btc')
                x_parts.append(frame)
                y_parts.append(asset['target'][asset['train']])
                w_parts.append(asset['weights'][asset['train']])
            x=pd.concat(x_parts,ignore_index=True)
            y=np.concatenate(y_parts);weights=np.concatenate(w_parts)
            xval=assets['btc']['features'].loc[val].copy()
            if pool=='btc_eth_indicator':
                xval['asset_is_btc']=1.
            for recipe in models:
                name=pool+'__'+recipe['name']
                folder=output/name;folder.mkdir()
                print(f'Fitting {name}, train_n={len(y)}',flush=True)
                model=make_model(recipe)
                model.fit(x,y,sample_weight=weights)
                predicted=model.predict(xval)*assets['btc']['scale'][val]
                joblib.dump(model,folder/'model.joblib')
                np.testing.assert_array_equal(predicted,joblib.load(folder/'model.joblib').predict(xval)*assets['btc']['scale'][val])
                saved=bm.loc[val].copy()
                saved['partition']=np.where(masks['early_stop'].loc[val],'early_stop','selection')
                saved['predicted_log_return']=predicted
                saved.to_csv(folder/'predictions.csv',index=False,float_format='%.17g')
                seal(folder/'schema.json',list(x.columns))
                for multiplier in plan['multipliers']:
                    metrics={}
                    for part in ('early_stop','selection'):
                        mask=saved.partition.eq(part)
                        metrics[part]=metric(saved.loc[mask,'actual_log_return'].to_numpy(),predicted[mask]*multiplier)
                    rows.append(dict(name=name,multiplier=multiplier,metrics=metrics,train_n=len(y),
                        model_sha256=digest((folder/'model.joblib').read_bytes())))
                    print(f'  shrink={multiplier}: Relative MAE={metrics["selection"]["relative_mae"]:.6f}',flush=True)
    winner=min(rows,key=lambda r:r['metrics']['selection']['relative_mae'])
    seal(output/'report.json',dict(rows=rows,winner=winner,target_met=winner['metrics']['selection']['relative_mae']<=.97,
        reload_verified=True,test_2026_rows_used=0))
    print(f'WINNER {winner}',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--history',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,default=Path('data/models/hourly-transfer-research'))
    args=parser.parse_args()
    run(args.source,args.history,args.output_root)
