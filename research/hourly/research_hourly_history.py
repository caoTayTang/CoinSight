"""Fixed learning-history comparison for MAE learners, with longer ETH history."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
import shutil
from urllib.request import urlopen
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


def run(source,root):
    source,root=Path(source).resolve(),Path(root).resolve()
    original=unseal(source/'plan.json')
    snapshot=source/'development_snapshot.csv'
    if digest(snapshot.read_bytes())!=original['source_snapshot_sha256']:
        raise ValueError('BTC source changed')
    output=root/str(uuid4())
    output.mkdir(parents=True,exist_ok=False)
    models=[r for r in recipes() if r['family'] in ('cat','hist','xgb')]
    plan=dict(created_at=datetime.now(timezone.utc).isoformat(),source=str(source),goal_relative_mae=.97,
        source_snapshot_sha256=digest(snapshot.read_bytes()),train_starts=['2020-01-01','2022-01-01','2023-01-01','2024-01-01'],
        train_end='2025-01-01 exclusive',diagnostic='Jan-Jun 2025',selection='Jul-Dec 2025',
        recipes=models,sets=['compact','eth'],multipliers=[1.,.5],early_stopping=False,
        source_policy='ETH 1h monthly 2020-2025, SHA256 checked; all original validation hours required',
        test_2026_rows_used=0,scheduler=False,live_promotion=False,
        caveat='Reused selection with larger search budget; not unseen evidence')
    seal(output/'plan.json',plan)
    shutil.copy2(Path(__file__),output/'research_hourly_history.py')
    print(f'RUN={output}',flush=True)
    cache=output/'eth_archives'
    cache.mkdir()
    old=Path(original['cross_source'])
    known={r['url'].rsplit('/',1)[-1]:r for r in unseal(source/'eth_sources.json')}
    def read(month):
        filename=f'ETHUSDT-1h-{month}.zip'
        path=cache/filename
        url=f'https://data.binance.vision/data/spot/monthly/klines/ETHUSDT/1h/{filename}'
        if filename in known:
            expected=known[filename]['sha256']
            existing=old/'eth_archives'/filename
            if digest(existing.read_bytes())!=expected:
                raise ValueError('Existing ETH archive changed')
            shutil.copy2(existing,path)
        else:
            with urlopen(url+'.CHECKSUM',timeout=30) as response:
                expected=response.read().decode().split()[0]
            with urlopen(url,timeout=30) as response:
                content=response.read()
            if digest(content)!=expected:
                raise ValueError('ETH checksum mismatch')
            path.write_bytes(content)
        frame=pd.DataFrame(parse_kline_csv(read_zip_csv(path)))
        frame['open_time']=pd.to_datetime(frame.open_time,utc=True)
        if not frame.open_time.dt.strftime('%Y-%m').eq(month).all():
            raise ValueError('Wrong ETH archive month')
        return frame,dict(url=url,sha256=expected,path=str(path.relative_to(output)))
    with ThreadPoolExecutor(max_workers=4) as executor:
        results=list(executor.map(read,pd.period_range('2020-01','2025-12',freq='M').astype(str)))
    seal(output/'eth_sources.json',[r[1] for r in results])
    eth=pd.concat([r[0] for r in results],ignore_index=True)
    btc=pd.read_csv(snapshot,float_precision='round_trip')
    btc['open_time']=pd.to_datetime(btc.open_time,utc=True)
    if btc.open_time.ge(pd.Timestamp('2026-01-01',tz='UTC')).any() or eth.open_time.ge(pd.Timestamp('2026-01-01',tz='UTC')).any():
        raise ValueError('Test data forbidden')
    base,meta,_=feature_sets(btc)
    cross=build_cross_inputs(btc,eth).reindex(meta.index)
    features={'compact':base['compact'],'eth':pd.concat([base['compact'],cross],axis=1)}
    masks=development_splits(meta)
    val=masks['early_stop']|masks['selection']
    if val.sum()!=8760 or masks['selection'].sum()!=4416 or cross.loc[val].isna().any().any():
        raise ValueError('Original validation cannot be filtered')
    common=cross.notna().all(axis=1)
    y=meta.actual_log_return*10000
    rows=[]
    with threadpool_limits(limits=2):
        for set_name,frame in features.items():
            for start in plan['train_starts']:
                train=masks['train']&meta.target_open_time.ge(pd.Timestamp(start,tz='UTC'))&common
                for recipe in models:
                    name=f'{set_name}__{start}__{recipe["name"]}'
                    folder=output/name
                    folder.mkdir()
                    print(f'Fitting {name}, train_n={int(train.sum())}',flush=True)
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
                            mask=saved.partition.eq(part)
                            metrics[part]=metric(saved.loc[mask,'actual_log_return'].to_numpy(),predicted[mask]*multiplier)
                        rows.append(dict(name=name,multiplier=multiplier,train_n=int(train.sum()),metrics=metrics,
                                         model_sha256=digest((folder/'model.joblib').read_bytes())))
                        print(f'  shrink={multiplier}: Relative MAE={metrics["selection"]["relative_mae"]:.6f}',flush=True)
    winner=min(rows,key=lambda r:r['metrics']['selection']['relative_mae'])
    seal(output/'report.json',dict(rows=rows,winner=winner,target_met=winner['metrics']['selection']['relative_mae']<=.97,
                                  reload_verified=True,test_2026_rows_used=0))
    print(f'WINNER {winner}',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,default=Path('data/models/hourly-history-research'))
    args=parser.parse_args()
    run(args.source,args.output_root)
