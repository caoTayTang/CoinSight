"""Replay every saved validation trial without fitting or reading 2026 data."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from pipeline.decision.hourly_engineering import feature_sets
from pipeline.decision.hourly_model import sha256, write_json
from pipeline.decision.hourly_tuning import (TEST_START, development_splits, inverse_target_scale,
                                           predict_candidate, predict_raw)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    args=parser.parse_args()
    run=args.run_dir
    report=json.loads((run/'report.json').read_text())
    plan=json.loads((run/'plan.json').read_text())
    snapshot=run/'development_snapshot.csv'
    if sha256(snapshot)!=plan['snapshot_sha256']:
        raise ValueError('Development snapshot hash mismatch')
    frame=pd.read_csv(snapshot,float_precision='round_trip')
    frame['open_time']=pd.to_datetime(frame.open_time,utc=True)
    if (frame.open_time>=TEST_START).any():
        raise ValueError('Test data found in development snapshot')
    sets,meta,_=feature_sets(frame)
    masks=development_splits(meta)
    val=masks['early_stop']|masks['selection']
    verified=0
    for trial in report['trials']:
        folder=run/trial['name']
        recipe=json.loads((folder/'config.json').read_text())
        if sha256(folder/'model.ubj')!=trial['model_sha256']:
            raise ValueError(f'Model hash mismatch: {trial["name"]}')
        model=XGBRegressor(); model.load_model(folder/'model.ubj')
        features=sets[recipe['feature_set']].loc[val]
        if model.get_booster().feature_names!=list(features.columns):
            raise ValueError('Feature schema mismatch')
        scale=inverse_target_scale(recipe['target_transform'],sets['base']).loc[val]
        saved=pd.read_csv(folder/'validation_predictions.csv',float_precision='round_trip')
        times=pd.to_datetime(saved.target_open_time,utc=True)
        if (times>=TEST_START).any() or not times.equals(meta.loc[val,'target_open_time'].reset_index(drop=True)):
            raise ValueError('Prediction timestamps differ or include test')
        actual=predict_raw(model,features,scale)
        np.testing.assert_array_equal(actual,saved.predicted_log_return.to_numpy())
        np.testing.assert_array_equal(saved.actual_log_return.to_numpy(),meta.loc[val,'actual_log_return'].to_numpy())
        verified+=len(actual)
    selected=json.loads((run/'selected_recipe.json').read_text())
    if sha256(run/'selected_model.ubj')!=selected['model_sha256']:
        raise ValueError('Selected artifact hash mismatch')
    last_input=meta.loc[val,'input_open_time'].max()
    context=frame.loc[frame.open_time<=last_input].tail(169)
    predicted=predict_candidate(run,context)
    selected_predictions=pd.read_csv(run/selected['name']/'validation_predictions.csv',float_precision='round_trip')
    np.testing.assert_allclose(predicted,selected_predictions.predicted_log_return.iloc[-1],rtol=1e-7,atol=1e-10)
    evidence={'checked_at':datetime.now(timezone.utc),'trials_verified':len(report['trials']),
              'predictions_replayed_exactly':verified,'snapshot_sha256_verified':True,
              'selected_inference_without_target_verified':True,'test_rows_used':0}
    write_json(run/'independent_checks.json',evidence)
    print(json.dumps({k:str(v) if isinstance(v,datetime) else v for k,v in evidence.items()},indent=2))


if __name__=='__main__':
    main()
