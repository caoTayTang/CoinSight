"""Train-only volatility/trend experts with fixed blending on all validation hours."""
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
from pipeline.decision.hourly_tuning import development_splits
from research.hourly.research_hourly_calibration import optimal_shrink,past_mask
from research.hourly.research_hourly_mae import make_model,metric,recipes


def regime_ids(vol,trend,train):
    vol,trend=np.asarray(vol),np.asarray(trend)
    if not np.isfinite(vol).all() or not np.isfinite(trend).all():
        raise ValueError('Regime variables must be available at cutoff')
    cuts={'volatility':np.quantile(vol[train],[1/3,2/3]).tolist(),
          'trend':np.quantile(trend[train],[1/3,2/3]).tolist()}
    vb=np.digitize(vol,cuts['volatility'])
    tb=np.digitize(trend,cuts['trend'])
    return {'volatility':vb,'trend':tb,'volatility_trend':3*vb+tb},cuts


def run(source,history,root):
    source,history,root=(Path(p).resolve() for p in (source,history,root))
    old=unseal(source/'plan.json')
    snapshot=source/'development_snapshot.csv'
    if digest(snapshot.read_bytes())!=old['source_snapshot_sha256']:
        raise ValueError('BTC snapshot changed')
    output=root/str(uuid4())
    output.mkdir(parents=True,exist_ok=False)
    models=[r for r in recipes() if r['family'] in ('cat','hist')]
    plan=dict(created_at=datetime.now(timezone.utc).isoformat(),goal_relative_mae=.97,
        source=str(source),history_source=str(history),source_snapshot_sha256=digest(snapshot.read_bytes()),
        train='2023-2024',gates=['volatility','trend','volatility_trend'],
        thresholds='Train-only tertiles of return std24 and vol-normalized momentum24',
        minimum_expert_train_rows=500,rare_regime_policy='Fallback to existing global model; keep every target',
        recipes=models,expert_blends=[.5,1.],slopes=['fixed_05','jan_jun_calibrated'],
        calibration_label_publication_lag_hours=1,selection='All 4416 original Jul-Dec 2025 hours',
        test_2026_rows_used=0,scheduler=False,live_promotion=False,
        caveat='Additional selection on repeatedly inspected validation; not unseen evidence')
    seal(output/'plan.json',plan)
    shutil.copy2(Path(__file__),output/'research_hourly_regimes.py')
    print(f'RUN={output}',flush=True)
    btc=pd.read_csv(snapshot,float_precision='round_trip')
    btc.open_time=pd.to_datetime(btc.open_time,utc=True)
    if btc.open_time.ge(pd.Timestamp('2026-01-01',tz='UTC')).any():
        raise ValueError('Test data forbidden')
    base,meta,_=feature_sets(btc)
    features=base['compact']
    masks=development_splits(meta)
    train=(masks['train']&meta.target_open_time.ge(pd.Timestamp('2023-01-01',tz='UTC'))).to_numpy()
    val=(masks['early_stop']|masks['selection']).to_numpy()
    if train.sum()!=17374 or val.sum()!=8760:
        raise ValueError('Original sample counts changed')
    groups,cuts=regime_ids(features.return_std_24,features.vol_normalized_momentum_24,train)
    seal(output/'gates.json',cuts)
    metadata=meta.loc[val].copy()
    metadata['partition']=np.where(masks['early_stop'].loc[val],'early_stop','selection')
    calibration=past_mask(metadata,pd.Timestamp('2025-07-01',tz='UTC'))
    y=meta.actual_log_return.to_numpy()*10000
    rows=[]
    fit_count=0
    old_report=unseal(history/'report.json')
    with threadpool_limits(limits=2):
        for recipe in models:
            global_name='compact__2023-01-01__'+recipe['name']
            oldrow=next(r for r in old_report['rows'] if r['name']==global_name)
            global_path=history/global_name/'model.joblib'
            if digest(global_path.read_bytes())!=oldrow['model_sha256']:
                raise ValueError('Global model changed')
            global_model=joblib.load(global_path)
            global_pred=global_model.predict(features.loc[val])/10000
            original=pd.read_csv(history/global_name/'predictions.csv',float_precision='round_trip')
            np.testing.assert_array_equal(global_pred,original.predicted_log_return.to_numpy())
            for gate,ids in groups.items():
                routed=global_pred.copy()
                evidence=[]
                for group in sorted(np.unique(ids[val])):
                    expert_train=train&(ids==group)
                    expert_val=ids[val]==group
                    if expert_train.sum()<500:
                        evidence.append(dict(regime=int(group),train_n=int(expert_train.sum()),fallback=True))
                        continue
                    folder=output/recipe['name']/gate/str(group)
                    folder.mkdir(parents=True)
                    model=make_model(recipe)
                    model.fit(features.loc[expert_train],y[expert_train])
                    pred=model.predict(features.loc[val].loc[expert_val])/10000
                    routed[expert_val]=pred
                    joblib.dump(model,folder/'model.joblib')
                    np.testing.assert_array_equal(pred,joblib.load(folder/'model.joblib').predict(features.loc[val].loc[expert_val])/10000)
                    fit_count+=1
                    evidence.append(dict(regime=int(group),train_n=int(expert_train.sum()),fallback=False,
                        path=str(folder.relative_to(output)),model_sha256=digest((folder/'model.joblib').read_bytes())))
                seal(output/(recipe['name']+'__'+gate+'_experts.json'),evidence)
                for blend in plan['expert_blends']:
                    pred=(1-blend)*global_pred+blend*routed
                    learned=optimal_shrink(metadata.loc[calibration,'actual_log_return'],pred[calibration])
                    for kind,alpha in [('fixed_05',.5),('jan_jun_calibrated',learned)]:
                        name=f'{recipe["name"]}__{gate}__blend{blend}__{kind}'
                        saved=metadata.copy()
                        saved['predicted_log_return']=pred*alpha
                        saved.to_csv(output/(name+'_predictions.csv'),index=False,float_format='%.17g')
                        metrics={}
                        for part in ('early_stop','selection'):
                            selected=saved.partition.eq(part)
                            metrics[part]=metric(saved.loc[selected,'actual_log_return'].to_numpy(),saved.loc[selected,'predicted_log_return'].to_numpy())
                        rows.append(dict(name=name,alpha=float(alpha),metrics=metrics))
                        print(f'{name}: Relative MAE={metrics["selection"]["relative_mae"]:.6f}',flush=True)
    winner=min(rows,key=lambda r:r['metrics']['selection']['relative_mae'])
    seal(output/'report.json',dict(rows=rows,winner=winner,expert_fits=fit_count,
        target_met=winner['metrics']['selection']['relative_mae']<=.97,reload_verified=True,test_2026_rows_used=0))
    print(f'WINNER {winner}',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--history',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,default=Path('data/models/hourly-regime-research'))
    args=parser.parse_args()
    run(args.source,args.history,args.output_root)
