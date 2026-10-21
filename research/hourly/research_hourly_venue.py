"""Bounded fixed cross-venue experiment; all original BTC evaluation hours retained."""
import argparse
from datetime import datetime,timezone
from pathlib import Path
import shutil,time
from uuid import uuid4
import joblib
import numpy as np
import pandas as pd
import requests
from threadpoolctl import threadpool_limits
from pipeline.decision.hourly_engineering import feature_sets
from pipeline.decision.hourly_future import seal,unseal,digest
from pipeline.decision.hourly_tuning import development_splits
from pipeline.decision.hourly_venue import parse_coinbase,venue_inputs
from research.hourly.research_hourly_mae import recipes,make_model,metric


def run(source,root,cache):
    source,root,cache=(Path(p).resolve() for p in (source,root,cache));cache.mkdir(parents=True,exist_ok=True)
    snapshot=source/'development_snapshot.csv';assert digest(snapshot.read_bytes())==unseal(source/'plan.json')['source_snapshot_sha256']
    out=root/str(uuid4());out.mkdir(parents=True)
    model_recipes=[r for r in recipes() if r['family'] in ('cat','hist')]
    plan=dict(created_at=datetime.now(timezone.utc).isoformat(),source=str(source),snapshot_sha256=digest(snapshot.read_bytes()),
        goal_relative_mae=.97,train='2024 only',diagnostic='Jan-Jun 2025',selection='All original 4416 Jul-Dec 2025 BTC hours',
        product='BTC-USD',api='https://api.exchange.coinbase.com',granularity=3600,request_hours=288,
        start='2023-12-18T00:00:00Z',end_exclusive='2026-01-01T00:00:00Z',spacing_seconds=1,
        max_download_bytes=10*1024**2,max_collection_seconds=600,
        sets=['compact_control','compact_coinbase_lag0','compact_coinbase_lag1'],recipes=model_recipes,
        multipliers=[1.,.5],no_early_stopping=True,threads=2,test_2026_rows_used=0,scheduler=False,live_promotion=False,
        caveat='Retrospective revised exchange candles; closed-hour assumption and +1h sensitivity. USD/USDT basis is not pure venue premium or order flow.')
    seal(out/'plan.json',plan);shutil.copy2(__file__,out/Path(__file__).name)
    shutil.copy2('pipeline/decision/hourly_venue.py',out/'hourly_venue.py')
    print(f'RUN={out}',flush=True)
    frames=[];entries=[];total=0;last=0;began=time.monotonic();session=requests.Session()
    stop=pd.Timestamp(plan['end_exclusive'])
    for i,start in enumerate(pd.date_range(plan['start'],stop,freq='288h',inclusive='left')):
        if time.monotonic()-began>600: raise RuntimeError('Collection time quota exceeded')
        end=min(start+pd.Timedelta(hours=288),stop)
        params=dict(granularity=3600,start=start.isoformat(),end=end.isoformat());f=cache/f'{start:%Y%m%d%H}_{end:%Y%m%d%H}.json'
        if f.exists():
            record=unseal(f)
            if record['params']!=params: raise ValueError('Cached request mismatch')
        else:
            time.sleep(max(0,1-(time.monotonic()-last)));last=time.monotonic()
            response=session.get(plan['api']+'/products/BTC-USD/candles',params=params,timeout=25)
            response.raise_for_status()
            if len(response.content)>200000: raise ValueError('Oversized response')
            record=dict(params=params,url=response.url,fetched_at=datetime.now(timezone.utc).isoformat(),rows=response.json())
            parse_coinbase(record['rows']);seal(f,record)
        frame=parse_coinbase(record['rows']);frame=frame[frame.open_time.ge(start)&frame.open_time.lt(end)]
        frames.append(frame);total+=f.stat().st_size
        if total>plan['max_download_bytes']: raise RuntimeError('Download quota exceeded')
        entries.append(dict(path=str(f),sha256=digest(f.read_bytes()),url=record['url']))
        if i%10==0: print(f'Fetched {i+1} chunks through {end.date()}',flush=True)
    cb=pd.concat(frames,ignore_index=True)
    if cb.open_time.duplicated().any() or cb.open_time.ge(stop).any(): raise ValueError('Invalid collected time range')
    cb.to_csv(out/'coinbase_candles.csv',index=False,float_format='%.17g');seal(out/'sources.json',entries)
    btc=pd.read_csv(snapshot,float_precision='round_trip');btc.open_time=pd.to_datetime(btc.open_time,utc=True)
    base,meta,_=feature_sets(btc);masks=development_splits(meta);val=masks['early_stop']|masks['selection']
    train=meta.target_open_time.ge(pd.Timestamp('2024-01-01',tz='UTC'))&meta.target_open_time.lt(pd.Timestamp('2025-01-01',tz='UTC'))
    assert masks['selection'].sum()==4416
    sets={'compact_control':base['compact']}
    for lag in (0,1):
        extra=venue_inputs(btc,cb,lag).reindex(meta.index)
        sets[f'compact_coinbase_lag{lag}']=pd.concat([base['compact'],extra],axis=1)
    if any(not x.index.equals(meta.index) for x in sets.values()):
        raise ValueError('Feature sets must share original metadata index')
    rows=[]
    with threadpool_limits(limits=2):
        for name,x in sets.items():
            coverage=float(x.loc[val].notna().all(axis=1).mean())
            for recipe in model_recipes:
                key=name+'__'+recipe['name'];folder=out/key;folder.mkdir()
                print(f'Fitting {key}: coverage={coverage:.4f}',flush=True)
                model=make_model(recipe);model.fit(x.loc[train],meta.loc[train,'actual_log_return']*10000)
                pred=model.predict(x.loc[val])/10000;joblib.dump(model,folder/'model.joblib')
                np.testing.assert_array_equal(pred,joblib.load(folder/'model.joblib').predict(x.loc[val])/10000)
                d=meta.loc[val].copy();d['partition']=np.where(masks['early_stop'][val],'early_stop','selection');d['predicted_log_return']=pred
                d.to_csv(folder/'predictions.csv',index=False,float_format='%.17g');seal(folder/'schema.json',list(x.columns))
                for multiplier in (1.,.5):
                    metrics={}
                    for part in ('early_stop','selection'):
                        a=d[d.partition.eq(part)];metrics[part]=metric(a.actual_log_return.to_numpy(),a.predicted_log_return.to_numpy()*multiplier)
                    rows.append(dict(name=key,multiplier=multiplier,metrics=metrics,coverage=coverage,model_sha256=digest((folder/'model.joblib').read_bytes())))
                    print(f'  factor={multiplier}: {metrics["selection"]["relative_mae"]:.6f}',flush=True)
    winner=min(rows,key=lambda r:r['metrics']['selection']['relative_mae'])
    seal(out/'report.json',dict(rows=rows,winner=winner,target_met=winner['metrics']['selection']['relative_mae']<=.97,
        original_selection_n=4416,reload_verified=True,test_2026_rows_used=0,source_bytes=total,source_candles=len(cb)))
    print(f'WINNER={winner}',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output-root',type=Path,default=Path('data/models/hourly-venue-research'))
    p.add_argument('--cache',type=Path,default=Path('data/models/hourly-venue-sources'))
    a=p.parse_args();run(a.source,a.output_root,a.cache)
