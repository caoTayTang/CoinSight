"""Fit ensemble weights on Jan-Jun predictions, never on Jul-Dec scoring labels."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
from uuid import uuid4

import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy.sparse import csr_matrix, eye, hstack, vstack
from sklearn.linear_model import QuantileRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
import joblib
from threadpoolctl import threadpool_limits

from pipeline.decision.hourly_future import digest, seal, unseal
from research.hourly.research_hourly_mae import metric


def positive_mae_weights(x,y,penalty):
    n,m=x.shape
    matrix=csr_matrix(x)
    slack=eye(n,format='csr')
    inequalities=vstack([hstack([matrix,-slack]),hstack([-matrix,-slack]),
                         hstack([csr_matrix(np.ones((1,m))),csr_matrix((1,n))])],format='csr')
    target=np.r_[y,-y,2.]
    objective=np.r_[np.full(m,penalty),np.full(n,1/n)]
    result=linprog(objective,A_ub=inequalities,b_ub=target,bounds=[(0,2)]*m+[(0,None)]*n,method='highs')
    if not result.success:
        raise ValueError(result.message)
    return result.x[:m]


def run(sources,root,label_lag_hours=1):
    sources=[Path(p).resolve() for p in sources]
    output=Path(root).resolve()/str(uuid4())
    output.mkdir(parents=True,exist_ok=False)
    seal(output/'plan.json',dict(created_at=datetime.now(timezone.utc).isoformat(),sources=list(map(str,sources)),
        weights_fit='Jan-Jun 2025 only',label_publication_lag_hours=label_lag_hours,
        selection='Jul-Dec 2025, all 4416 original hours',
        variants=['positive_mae_penalty0','positive_mae_penalty005','median_linear_alpha0005',
                  'median_linear_alpha005','equal_mean_half','median_half'],
        nonnegative_weight_sum_limit=2.,prediction_units='bps for meta fit; raw return for metrics',
        goal_relative_mae=.97,test_2026_rows_used=0,scheduler=False,
        caveat='Base models fit on pre-2025 labels; source recipes and selection already viewed repeatedly'))
    shutil.copy2(Path(__file__),output/'research_hourly_ensemble.py')
    print(f'RUN={output}',flush=True)
    reference=None
    columns={}
    hashes=set()
    for source in sources:
        report=unseal(source/'report.json')
        for row in report['rows']:
            if row['multiplier']!=1.:
                continue
            if digest((source/row['name']/'model.joblib').read_bytes())!=row['model_sha256']:
                raise ValueError('Base model changed')
            path=source/row['name']/'predictions.csv'
            frame=pd.read_csv(path,float_precision='round_trip')
            if reference is None:
                reference=frame.drop(columns='predicted_log_return')
            else:
                pd.testing.assert_frame_equal(frame.drop(columns='predicted_log_return'),reference)
            vector=frame.predicted_log_return.to_numpy()
            identity=digest(vector.tobytes())
            if identity not in hashes:
                hashes.add(identity)
                columns[str(source/row['name'])]=vector
    x=np.column_stack(list(columns.values()))*10000
    y=reference.actual_log_return.to_numpy()*10000
    first=pd.to_datetime(reference.loc[reference.partition.eq('selection'),'cutoff_time'],utc=True).min()
    closed=pd.to_datetime(reference.target_close_time,utc=True)
    train=(reference.partition.eq('early_stop')&closed.le(first-pd.Timedelta(hours=label_lag_hours))).to_numpy()
    selection=reference.partition.eq('selection').to_numpy()
    if train.sum()!=4344-label_lag_hours or selection.sum()!=4416:
        raise ValueError('Unexpected metadata partitions')
    seal(output/'members.json',list(columns))
    rows=[]
    with threadpool_limits(limits=2):
        for name in ['positive_mae_penalty0','positive_mae_penalty005','median_linear_alpha0005',
                     'median_linear_alpha005','equal_mean_half','median_half']:
            if name.startswith('positive'):
                penalty=0. if name.endswith('penalty0') else .05
                weights=positive_mae_weights(x[train],y[train],penalty)
                prediction=x@weights/10000
                seal(output/(name+'_weights.json'),weights.tolist())
            elif name.startswith('median_linear'):
                alpha=.005 if name.endswith('0005') else .05
                model=make_pipeline(StandardScaler(),QuantileRegressor(alpha=alpha,quantile=.5,solver='highs'))
                model.fit(x[train],y[train])
                prediction=model.predict(x)/10000
                joblib.dump(model,output/(name+'.joblib'))
                np.testing.assert_array_equal(prediction,joblib.load(output/(name+'.joblib')).predict(x)/10000)
            elif name=='equal_mean_half':
                prediction=x.mean(axis=1)*.5/10000
            else:
                prediction=np.median(x,axis=1)*.5/10000
            saved=reference.copy()
            saved['predicted_log_return']=prediction
            saved.to_csv(output/(name+'_predictions.csv'),index=False,float_format='%.17g')
            summary={part:metric(y[mask]/10000,prediction[mask]) for part,mask in [('meta_train',train),('selection',selection)]}
            rows.append(dict(name=name,metrics=summary))
            print(name,summary,flush=True)
    winner=min(rows,key=lambda r:r['metrics']['selection']['relative_mae'])
    seal(output/'report.json',dict(rows=rows,winner=winner,members=len(columns),
        calibration_n=int(train.sum()),last_calibration_label_close=closed[train].max().isoformat(),
        target_met=winner['metrics']['selection']['relative_mae']<=.97,test_2026_rows_used=0))
    print(f'WINNER {winner}',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources',type=Path,nargs='+',required=True)
    parser.add_argument('--output-root',type=Path,default=Path('data/models/hourly-ensemble-research'))
    parser.add_argument('--label-lag-hours',type=int,choices=[0,1],default=1)
    args=parser.parse_args()
    run(args.sources,args.output_root,args.label_lag_hours)
