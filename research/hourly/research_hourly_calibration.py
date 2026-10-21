"""Past-label-only shrinkage and ensembles on unchanged Jul-Dec BTC return targets."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from uuid import uuid4

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from pipeline.decision.hourly_future import digest,seal,unseal
from research.hourly.research_hourly_ensemble import positive_mae_weights
from research.hourly.research_hourly_mae import metric


def optimal_shrink(actual,predicted):
    """Exact MAE-optimal nonnegative slope in [0,2] via weighted median, no test fit."""
    actual,predicted=np.asarray(actual),np.asarray(predicted)
    if actual.shape!=predicted.shape or not np.isfinite(actual).all() or not np.isfinite(predicted).all():
        raise ValueError('Calibration needs finite aligned observations')
    useful=np.abs(predicted)>1e-12
    if not useful.any():
        return 0.
    ratios=actual[useful]/predicted[useful]
    weights=np.abs(predicted[useful])
    order=np.argsort(ratios,kind='stable')
    chosen=np.searchsorted(np.cumsum(weights[order]),weights.sum()/2,side='left')
    return float(np.clip(ratios[order[min(chosen,len(order)-1)]],0.,2.))


def past_mask(meta,cutoff,days=None):
    """An entire hour of label publication margin; never use a current/future label."""
    cutoff=pd.Timestamp(cutoff)
    mask=meta.target_close_time.le(cutoff-pd.Timedelta(hours=1))
    if days is not None:
        mask &= meta.target_open_time.ge(cutoff-pd.Timedelta(days=days))
    return mask.to_numpy()


def run(history,mae,optuna,root):
    history,mae,optuna,root=(Path(p).resolve() for p in (history,mae,optuna,root))
    members=[('btc_history',history/'compact__2023-01-01__cat_median_d6/predictions.csv'),
             ('eth_history',history/'eth__2023-01-01__cat_median_d6/predictions.csv'),
             ('eth_recent',mae/'eth__cat_mae_d4/predictions.csv'),
             ('xgb_reference',optuna/'trial_041/validation_predictions.csv')]
    output=root/str(uuid4())
    output.mkdir(parents=True,exist_ok=False)
    plan=dict(created_at=datetime.now(timezone.utc).isoformat(),goal_relative_mae=.97,
        members=[dict(name=n,path=str(p),sha256=digest(p.read_bytes())) for n,p in members],
        static_calibration='Jan-Jun 2025 with target close <= Jul 1 cutoff minus one hour',
        rolling_calibration='Daily slope or monthly ensemble; use only labels closed >=1h before update cutoff',
        scalar_days=[7,30,90,180],scalar_smoothing=.5,scalar_bounds=[0.,2.],
        ensemble_days=[30,90,180],ensemble_smoothing=.5,ensemble_weight_sum_limit=2.,ensemble_weight_penalty_bps=.05,
        selection='All original 4416 Jul-Dec 2025 hours; zero-return baseline',
        test_2026_rows_used=0,scheduler=False,live_promotion=False,
        caveat='Chronological online updates consume prior selection labels; selection already inspected repeatedly')
    seal(output/'plan.json',plan)
    shutil.copy2(Path(__file__),output/'research_hourly_calibration.py')
    print(f'RUN={output}',flush=True)
    reference=None
    vectors=[]
    for name,path in members:
        frame=pd.read_csv(path,float_precision='round_trip')
        other=frame.drop(columns='predicted_log_return')
        if reference is None:
            reference=other
        else:
            pd.testing.assert_frame_equal(reference,other)
        vectors.append(frame.predicted_log_return.to_numpy())
    meta=reference.copy()
    for column in ('target_open_time','target_close_time','cutoff_time'):
        meta[column]=pd.to_datetime(meta[column],utc=True)
    if not meta.target_open_time.between(pd.Timestamp('2025-01-01',tz='UTC'),pd.Timestamp('2026-01-01',tz='UTC'),inclusive='left').all():
        raise ValueError('Unexpected validation dates')
    selection=meta.partition.eq('selection').to_numpy()
    if len(meta)!=8760 or selection.sum()!=4416:
        raise ValueError('Original validation rows changed')
    x=np.column_stack(vectors)
    y=meta.actual_log_return.to_numpy()
    first=pd.Timestamp('2025-07-01',tz='UTC')
    static_train=past_mask(meta,first)
    if static_train.sum()!=4343:
        raise ValueError('Unexpected calibration count with one-hour publication margin')
    static_alpha=np.array([optimal_shrink(y[static_train],x[static_train,j]) for j in range(len(members))])
    seal(output/'static_slopes.json',dict(zip([m[0] for m in members],static_alpha)))
    rows=[]
    def save(name,predicted,evidence):
        selected=predicted[selection]
        score=metric(y[selection],selected)
        saved=reference.loc[selection].copy()
        saved['predicted_log_return']=selected
        saved.to_csv(output/(name+'_predictions.csv'),index=False,float_format='%.17g')
        seal(output/(name+'_updates.json'),evidence)
        rows.append(dict(name=name,metrics=score))
        print(name,score,flush=True)
    for j,(name,_) in enumerate(members):
        save(name+'__static',x[:,j]*static_alpha[j],[dict(update=first.isoformat(),n=int(static_train.sum()),alpha=float(static_alpha[j]),
            last_label_close=meta.loc[static_train,'target_close_time'].max().isoformat())])
        for days in plan['scalar_days']:
            prediction=np.full(len(meta),np.nan)
            updates=[]
            for day in pd.date_range(first,pd.Timestamp('2025-12-31',tz='UTC'),freq='D'):
                train=past_mask(meta,day,days)
                if train.sum()<100:
                    raise ValueError('Insufficient calibration history')
                recent=optimal_shrink(y[train],x[train,j])
                alpha=.5*static_alpha[j]+.5*recent
                val=meta.target_open_time.ge(day)&meta.target_open_time.lt(day+pd.Timedelta(days=1))
                prediction[val]=x[val,j]*alpha
                updates.append(dict(update=day.isoformat(),n=int(train.sum()),alpha=float(alpha),
                    last_label_close=meta.loc[train,'target_close_time'].max().isoformat()))
            save(name+f'__daily_{days}',prediction,updates)
    with threadpool_limits(limits=2):
        global_weights=positive_mae_weights(x[static_train]*10000,y[static_train]*10000,.05)
        save('ensemble_static',x@global_weights,[dict(update=first.isoformat(),weights=global_weights.tolist(),
            n=int(static_train.sum()),last_label_close=meta.loc[static_train,'target_close_time'].max().isoformat())])
        for days in plan['ensemble_days']:
            prediction=np.full(len(meta),np.nan)
            updates=[]
            for month in pd.date_range(first,pd.Timestamp('2025-12-01',tz='UTC'),freq='MS'):
                train=past_mask(meta,month,days)
                weights=.5*global_weights+.5*positive_mae_weights(x[train]*10000,y[train]*10000,.05)
                val=meta.target_open_time.ge(month)&meta.target_open_time.lt(month+pd.DateOffset(months=1))
                prediction[val]=x[val]@weights
                updates.append(dict(update=month.isoformat(),weights=weights.tolist(),n=int(train.sum()),
                    last_label_close=meta.loc[train,'target_close_time'].max().isoformat()))
            save(f'ensemble_monthly_{days}',prediction,updates)
    winner=min(rows,key=lambda r:r['metrics']['relative_mae'])
    seal(output/'report.json',dict(rows=rows,winner=winner,target_met=winner['metrics']['relative_mae']<=.97,
        source_prediction_hashes_verified=True,label_lag_hours=1,test_2026_rows_used=0))
    print(f'WINNER {winner}',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history',type=Path,required=True)
    parser.add_argument('--mae',type=Path,required=True)
    parser.add_argument('--optuna',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,default=Path('data/models/hourly-calibration-research'))
    args=parser.parse_args()
    run(args.history,args.mae,args.optuna,args.output_root)
