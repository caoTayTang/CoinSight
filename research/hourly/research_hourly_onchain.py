"""Fixed small daily on-chain study, maintaining original BTC target and timestamps."""
import argparse
from datetime import datetime,timezone
from pathlib import Path
import shutil
from uuid import uuid4
import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from pipeline.decision.hourly_engineering import feature_sets
from pipeline.decision.hourly_future import digest,seal,unseal
from pipeline.decision.hourly_onchain import onchain_inputs
from pipeline.decision.hourly_tuning import development_splits
from research.hourly.research_hourly_mae import recipes,make_model,metric


def run(source,chain,root):
    source,chain,root=(Path(p).resolve() for p in (source,chain,root))
    snapshot=source/'development_snapshot.csv'
    assert digest(snapshot.read_bytes())==unseal(source/'plan.json')['source_snapshot_sha256']
    assert digest(chain.read_bytes())==unseal(chain.with_suffix('.json'))['sha256']
    out=root/str(uuid4());out.mkdir(parents=True)
    models=[r for r in recipes() if r['family']=='cat']
    plan=dict(created_at=datetime.now(timezone.utc).isoformat(),source=str(source),chain=str(chain),
              chain_sha256=digest(chain.read_bytes()),snapshot_sha256=digest(snapshot.read_bytes()),
              train='2024 only',diagnostic='Jan-Jun 2025',selection='All original 4416 Jul-Dec BTC hours',
              delays_hours=[48,72],sets=['network','network_flows'],recipes=models,multipliers=[1.,.5],
              availability='max(daily bucket start + delay, AssetEODCompletionTime)',
              revision_caveat='Historical current snapshot, especially exchange labels may be revised; not point-in-time proof',
              test_2026_rows_used=0,scheduler=False,live_promotion=False,threads=2)
    seal(out/'plan.json',plan);shutil.copy2(__file__,out/Path(__file__).name)
    shutil.copy2(Path('pipeline/decision/hourly_onchain.py'),out/'hourly_onchain.py')
    print(f'RUN={out}',flush=True)
    btc=pd.read_csv(snapshot,float_precision='round_trip');btc.open_time=pd.to_datetime(btc.open_time,utc=True)
    base,meta,_=feature_sets(btc);masks=development_splits(meta)
    train=meta.target_open_time.ge(pd.Timestamp('2024-01-01',tz='UTC'))&meta.target_open_time.lt(pd.Timestamp('2025-01-01',tz='UTC'))
    val=masks['early_stop']|masks['selection'];daily=pd.read_csv(chain)
    daily=daily[pd.to_datetime(daily.time,utc=True).lt(pd.Timestamp('2026-01-01',tz='UTC'))].copy()
    assert int(masks['selection'].sum())==4416
    rows=[]
    with threadpool_limits(limits=2):
        for delay in plan['delays_hours']:
            for name in plan['sets']:
                extra=onchain_inputs(daily,meta.cutoff_time,delay,flows=name=='network_flows')
                x=pd.concat([base['compact'],extra],axis=1)
                coverage=float(extra.loc[val].notna().all(axis=1).mean())
                for recipe in models:
                    key=f'{name}__delay{delay}__{recipe["name"]}';folder=out/key;folder.mkdir()
                    print(f'Fitting {key}: {x.shape[1]} features, coverage={coverage:.4f}',flush=True)
                    model=make_model(recipe);model.fit(x.loc[train],meta.loc[train,'actual_log_return']*10000)
                    pred=model.predict(x.loc[val])/10000
                    joblib.dump(model,folder/'model.joblib')
                    np.testing.assert_array_equal(pred,joblib.load(folder/'model.joblib').predict(x.loc[val])/10000)
                    d=meta.loc[val].copy();d['partition']=np.where(masks['early_stop'][val],'early_stop','selection');d['predicted_log_return']=pred
                    d.to_csv(folder/'predictions.csv',index=False,float_format='%.17g');seal(folder/'schema.json',list(x.columns))
                    for multiplier in plan['multipliers']:
                        metrics={}
                        for part in ('early_stop','selection'):
                            a=d[d.partition.eq(part)];metrics[part]=metric(a.actual_log_return.to_numpy(),a.predicted_log_return.to_numpy()*multiplier)
                        rows.append(dict(name=key,multiplier=multiplier,metrics=metrics,coverage=coverage,model_sha256=digest((folder/'model.joblib').read_bytes())))
                        print(f'  factor={multiplier}: {metrics["selection"]["relative_mae"]:.6f}',flush=True)
    winner=min(rows,key=lambda r:r['metrics']['selection']['relative_mae'])
    seal(out/'report.json',dict(rows=rows,winner=winner,target_met=winner['metrics']['selection']['relative_mae']<=.97,
                               reload_verified=True,point_in_time_verified=False,test_2026_rows_used=0))
    print(f'WINNER={winner}',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--chain',type=Path,required=True)
    p.add_argument('--output-root',type=Path,default=Path('data/models/hourly-onchain-research'))
    a=p.parse_args();run(a.source,a.chain,a.output_root)
