"""Fixed pre-July refit using newly available Jan-Jun labels; never fit selection labels."""
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
from pipeline.decision.hourly_tuning import development_splits
from research.hourly.research_hourly_mae import make_model,metric,recipes


def run(source,history,market,book,root):
    source,history,market,book,root=(Path(p).resolve() for p in (source,history,market,book,root))
    old=unseal(source/'plan.json');snapshot=source/'development_snapshot.csv'
    if digest(snapshot.read_bytes())!=old['source_snapshot_sha256']:
        raise ValueError('BTC snapshot changed')
    output=root/str(uuid4());output.mkdir(parents=True,exist_ok=False)
    models=[r for r in recipes() if r['family'] in ('cat','hist')]
    plan=dict(created_at=datetime.now(timezone.utc).isoformat(),source=str(source),history_source=str(history),
        market_source=str(market),book_source=str(book),goal_relative_mae=.97,
        snapshot_sha256=digest(snapshot.read_bytes()),
        market_features_sha256=digest((market/'market_features.csv').read_bytes()),
        book_features_sha256=digest((book/'bookdepth_features.csv').read_bytes()),
        train_starts=['2023-01-01','2024-01-01'],train_label_close_end='2025-06-30T23:00:00+00:00 inclusive',
        selection='BTC Jul-Dec 2025, all original 4416 hours; zero-return baseline',
        diagnostic_policy='Jan-Jun now training, not reported as validation; params fixed, no early stopping',
        sets=['compact','eth','eth_book','market_book'],recipes=models,multipliers=[1.,.5],
        test_2026_rows_used=0,scheduler=False,live_promotion=False,
        caveat='Retrospective chronology; more selection on previously viewed data; not unseen evidence')
    seal(output/'plan.json',plan)
    shutil.copy2(Path(__file__),output/'research_hourly_recent.py')
    print(f'RUN={output}',flush=True)
    btc=pd.read_csv(snapshot,float_precision='round_trip');btc.open_time=pd.to_datetime(btc.open_time,utc=True)
    eth=[]
    for item in unseal(history/'eth_sources.json'):
        path=history/item['path']
        if digest(path.read_bytes())!=item['sha256']: raise ValueError('ETH source changed')
        eth.append(pd.DataFrame(parse_kline_csv(read_zip_csv(path))))
    eth=pd.concat(eth,ignore_index=True);eth.open_time=pd.to_datetime(eth.open_time,utc=True)
    if btc.open_time.ge(pd.Timestamp('2026-01-01',tz='UTC')).any() or eth.open_time.ge(pd.Timestamp('2026-01-01',tz='UTC')).any():
        raise ValueError('Test data forbidden')
    base,meta,_=feature_sets(btc)
    masks=development_splits(meta);val=masks['selection'].to_numpy()
    if val.sum()!=4416: raise ValueError('Original selection changed')
    def cached(path):
        frame=pd.read_csv(path,index_col=0,float_precision='round_trip')
        frame.index=pd.to_datetime(frame.index,utc=True)
        return frame.reindex(meta.index)
    depth=cached(book/'bookdepth_features.csv');basket=cached(market/'market_features.csv')
    eth_features=pd.concat([base['compact'],build_cross_inputs(btc,eth).reindex(meta.index)],axis=1)
    features={'compact':base['compact'],'eth':eth_features,'eth_book':pd.concat([eth_features,depth],axis=1),
              'market_book':pd.concat([base['compact'],basket,depth],axis=1)}
    first=meta.loc[val,'cutoff_time'].min()
    rows=[]
    with threadpool_limits(limits=2):
        for start in plan['train_starts']:
            train=meta.target_open_time.ge(pd.Timestamp(start,tz='UTC'))&meta.target_close_time.le(first-pd.Timedelta(hours=1))
            assert not (train.to_numpy()&val).any()
            if meta.loc[train,'target_close_time'].max()>first-pd.Timedelta(hours=1):
                raise ValueError('Training label crosses publication cutoff')
            for set_name,frame in features.items():
                for recipe in models:
                    name=f'{start}__{set_name}__{recipe["name"]}'
                    folder=output/name;folder.mkdir()
                    print(f'Fitting {name}: n={int(train.sum())}',flush=True)
                    model=make_model(recipe)
                    model.fit(frame.loc[train],meta.loc[train,'actual_log_return']*10000)
                    predicted=model.predict(frame.loc[val])/10000
                    joblib.dump(model,folder/'model.joblib')
                    np.testing.assert_array_equal(predicted,joblib.load(folder/'model.joblib').predict(frame.loc[val])/10000)
                    saved=meta.loc[val].copy();saved['partition']='selection';saved['predicted_log_return']=predicted
                    saved.to_csv(folder/'predictions.csv',index=False,float_format='%.17g')
                    seal(folder/'schema.json',list(frame.columns))
                    seal(folder/'training_cutoff.json',dict(n=int(train.sum()),last_label_close=meta.loc[train,'target_close_time'].max().isoformat(),
                        first_selection_cutoff=first.isoformat(),label_publication_lag_hours=1))
                    for multiplier in plan['multipliers']:
                        metrics=metric(saved.actual_log_return.to_numpy(),predicted*multiplier)
                        rows.append(dict(name=name,multiplier=multiplier,metrics=metrics,train_n=int(train.sum()),
                            model_sha256=digest((folder/'model.joblib').read_bytes())))
                        print(f'  shrink={multiplier}: Relative MAE={metrics["relative_mae"]:.6f}',flush=True)
    winner=min(rows,key=lambda r:r['metrics']['relative_mae'])
    seal(output/'report.json',dict(rows=rows,winner=winner,target_met=winner['metrics']['relative_mae']<=.97,
        reload_verified=True,pre_selection_labels_only=True,test_2026_rows_used=0))
    print(f'WINNER {winner}',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--history',type=Path,required=True)
    parser.add_argument('--market',type=Path,required=True)
    parser.add_argument('--book',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,default=Path('data/models/hourly-recent-research'))
    args=parser.parse_args()
    run(args.source,args.history,args.market,args.book,args.output_root)
