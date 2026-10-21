"""Real depth-band archive inputs, with causal timestamp margins and fixed recipes."""
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
from pipeline.decision.hourly_bookdepth import book_inputs,load_bookdepth
from pipeline.decision.hourly_cross_asset import build_cross_inputs
from pipeline.decision.hourly_engineering import feature_sets
from pipeline.decision.hourly_future import digest,seal,unseal
from pipeline.decision.hourly_tuning import development_splits
from research.hourly.research_hourly_mae import make_model,metric,recipes


def run(source,history,market,cache,root):
    source,history,market,cache,root=(Path(p).resolve() for p in (source,history,market,cache,root))
    old=unseal(source/'plan.json');snapshot=source/'development_snapshot.csv'
    if digest(snapshot.read_bytes())!=old['source_snapshot_sha256']:
        raise ValueError('BTC snapshot changed')
    output=root/str(uuid4());output.mkdir(parents=True,exist_ok=False)
    models=[r for r in recipes() if r['family'] in ('cat','hist','xgb')]
    plan=dict(created_at=datetime.now(timezone.utc).isoformat(),source=str(source),history_source=str(history),
        market_source=str(market),goal_relative_mae=.97,snapshot_sha256=digest(snapshot.read_bytes()),
        market_features_sha256=digest((market/'market_features.csv').read_bytes()),
        archive_dates=['2023-12-30','2025-12-31'],archive_zip_limit_bytes=512*1024*1024,
        train_starts=['2023-01-01','2024-01-01'],train_end='2025-01-01 exclusive',
        source_history_policy='2023 train observations have depth missing; native missing handling; no target filtering',
        feature_sets=['eth','eth_book','market_book'],recipes=models,multipliers=[1.,.5],
        timestamp_policy='5min right-closed bins; latest bin <= cutoff minus 10min; max asof gap 15min',
        quality_policy='All six +/-1,2,5 bands positive finite; implied band price within 20% of already-closed spot reference; conflicting timestamps discarded',
        input_policy='Depth band quantities/notionals; not best bid/ask or actual executed order flow',
        selection='BTC Jul-Dec 2025 all original 4416 hours; zero-return baseline',
        test_2026_rows_used=0,scheduler=False,live_promotion=False,
        caveat='Reused selection; archives can contain exporter defects; reconstructed timestamps are not proven live availability')
    seal(output/'plan.json',plan)
    project=Path(__file__).resolve().parents[2]
    shutil.copy2(Path(__file__),output/'research_hourly_bookdepth.py')
    shutil.copy2(project/'pipeline/decision/hourly_bookdepth.py',output/'hourly_bookdepth.py')
    print(f'RUN={output}',flush=True)
    btc=pd.read_csv(snapshot,float_precision='round_trip');btc.open_time=pd.to_datetime(btc.open_time,utc=True)
    aggregate=load_bookdepth(output,cache,btc)
    extra=book_inputs(btc,aggregate)
    cutoff=pd.Timestamp('2025-06-01',tz='UTC')
    allowed=cutoff+pd.Timedelta(minutes=50)
    pd.testing.assert_frame_equal(extra.loc[:cutoff],book_inputs(btc[btc.open_time.le(cutoff)],aggregate.loc[:allowed]))
    extra.to_csv(output/'bookdepth_features.csv',float_format='%.17g')
    eth=[]
    for item in unseal(history/'eth_sources.json'):
        path=history/item['path']
        if digest(path.read_bytes())!=item['sha256']: raise ValueError('ETH archive changed')
        eth.append(pd.DataFrame(parse_kline_csv(read_zip_csv(path))))
    eth=pd.concat(eth,ignore_index=True);eth.open_time=pd.to_datetime(eth.open_time,utc=True)
    if btc.open_time.ge(pd.Timestamp('2026-01-01',tz='UTC')).any() or eth.open_time.ge(pd.Timestamp('2026-01-01',tz='UTC')).any():
        raise ValueError('Test candles forbidden')
    base,meta,_=feature_sets(btc)
    cross=build_cross_inputs(btc,eth).reindex(meta.index)
    other=pd.read_csv(market/'market_features.csv',index_col=0,float_precision='round_trip')
    other.index=pd.to_datetime(other.index,utc=True)
    baseline=pd.concat([base['compact'],cross],axis=1)
    frames={'eth':baseline,'eth_book':pd.concat([baseline,extra.reindex(meta.index)],axis=1),
            'market_book':pd.concat([base['compact'],other.reindex(meta.index),extra.reindex(meta.index)],axis=1)}
    masks=development_splits(meta);val=(masks['early_stop']|masks['selection']).to_numpy()
    if val.sum()!=8760 or masks['selection'].sum()!=4416: raise ValueError('Original validation changed')
    coverage={part:dict(n=int(mask.sum()),book_available_pct=float(extra.reindex(meta.index).loc[mask,'book_available'].mean()*100),
        all_book_fields_pct=float(extra.reindex(meta.index).loc[mask].notna().all(axis=1).mean()*100))
        for part,mask in [('diagnostic',masks['early_stop']),('selection',masks['selection'])]}
    seal(output/'source_coverage.json',coverage)
    print('Book depth coverage:',coverage,flush=True)
    rows=[]
    with threadpool_limits(limits=2):
        for start in plan['train_starts']:
            train=(masks['train']&meta.target_open_time.ge(pd.Timestamp(start,tz='UTC'))).to_numpy()
            for set_name,frame in frames.items():
                for recipe in models:
                    name=f'{start}__{set_name}__{recipe["name"]}'
                    folder=output/name;folder.mkdir()
                    print(f'Fitting {name}: n={int(train.sum())}, features={frame.shape[1]}',flush=True)
                    model=make_model(recipe)
                    model.fit(frame.loc[train],meta.loc[train,'actual_log_return']*10000)
                    predicted=model.predict(frame.loc[val])/10000
                    joblib.dump(model,folder/'model.joblib')
                    np.testing.assert_array_equal(predicted,joblib.load(folder/'model.joblib').predict(frame.loc[val])/10000)
                    saved=meta.loc[val].copy();saved['partition']=np.where(masks['early_stop'].loc[val],'early_stop','selection')
                    saved['predicted_log_return']=predicted
                    saved.to_csv(folder/'predictions.csv',index=False,float_format='%.17g')
                    seal(folder/'schema.json',list(frame.columns))
                    for multiplier in plan['multipliers']:
                        metrics={}
                        for part in ('early_stop','selection'):
                            chosen=saved.partition.eq(part)
                            metrics[part]=metric(saved.loc[chosen,'actual_log_return'].to_numpy(),predicted[chosen]*multiplier)
                        rows.append(dict(name=name,multiplier=multiplier,metrics=metrics,train_n=int(train.sum()),
                            model_sha256=digest((folder/'model.joblib').read_bytes())))
                        print(f'  shrink={multiplier}: Relative MAE={metrics["selection"]["relative_mae"]:.6f}',flush=True)
    winner=min(rows,key=lambda r:r['metrics']['selection']['relative_mae'])
    seal(output/'report.json',dict(rows=rows,winner=winner,target_met=winner['metrics']['selection']['relative_mae']<=.97,
        reload_verified=True,causal_prefix_verified=True,test_2026_rows_used=0))
    print(f'WINNER {winner}',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--history',type=Path,required=True)
    parser.add_argument('--market',type=Path,required=True)
    parser.add_argument('--cache',type=Path,default=Path('data/models/hourly-bookdepth-sources'))
    parser.add_argument('--output-root',type=Path,default=Path('data/models/hourly-bookdepth-research'))
    args=parser.parse_args()
    run(args.source,args.history,args.market,args.cache,args.output_root)
