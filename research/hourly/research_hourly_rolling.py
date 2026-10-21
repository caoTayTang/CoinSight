"""Fixed monthly refits with preceding labels only, scored on unchanged Jul-Dec hours."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
from uuid import uuid4

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from pipeline.batch.binance_archive_format import parse_kline_csv, read_zip_csv
from pipeline.decision.hourly_cross_asset import build_cross_inputs
from pipeline.decision.hourly_engineering import feature_sets
from pipeline.decision.hourly_future import digest, seal, unseal
from pipeline.decision.hourly_tuning import development_splits
from research.hourly.research_hourly_mae import make_model, metric, recipes


def run(source, root):
    source,root=Path(source).resolve(),Path(root).resolve()
    original=unseal(source/'plan.json')
    snapshot=source/'development_snapshot.csv'
    if digest(snapshot.read_bytes())!=original['source_snapshot_sha256']:
        raise ValueError('Source snapshot changed')
    output=root/str(uuid4())
    output.mkdir(parents=True,exist_ok=False)
    models=[r for r in recipes() if r['name'] in ('cat_mae_d4','hist_median')]
    plan=dict(created_at=datetime.now(timezone.utc).isoformat(),source=str(source),
        source_plan_sha256=digest((source/'plan.json').read_bytes()),goal_relative_mae=.97,
        sets=['eth','intrahour'],train_days=[90,365],transforms=['raw','vol24_weighted_mae'],
        recipes=models,multipliers=[1.,.5],months=['2025-07','2025-08','2025-09','2025-10','2025-11','2025-12'],
        policy='Fit at each month start on prior labels; no tuning within fold; all 4416 original selection hours',
        normalization='Causal 24h return std in bps, floor 1bp; weighted MAE by scale/mean(scale)',
        test_2026_rows_used=0,scheduler=False,live_promotion=False,
        caveat='Reused 2025 selection and additional model selection; not unseen evidence')
    seal(output/'plan.json',plan)
    shutil.copy2(Path(__file__),output/'research_hourly_rolling.py')
    print(f'RUN={output}',flush=True)
    btc=pd.read_csv(snapshot,float_precision='round_trip')
    btc['open_time']=pd.to_datetime(btc.open_time,utc=True)
    if btc.open_time.ge(pd.Timestamp('2026-01-01',tz='UTC')).any():
        raise ValueError('Test candles forbidden')
    cross_source=Path(original['cross_source'])
    eth=[]
    for item in unseal(source/'eth_sources.json'):
        path=cross_source/'eth_archives'/item['url'].rsplit('/',1)[-1]
        if digest(path.read_bytes())!=item['sha256']:
            raise ValueError('ETH source changed')
        eth.append(pd.DataFrame(parse_kline_csv(read_zip_csv(path))))
    eth=pd.concat(eth,ignore_index=True)
    eth['open_time']=pd.to_datetime(eth.open_time,utc=True)
    base,meta,_=feature_sets(btc)
    features={'eth':pd.concat([base['compact'],build_cross_inputs(btc,eth).reindex(meta.index)],axis=1)}
    intra=pd.read_csv(source/'intrahour_features.csv',index_col=0,float_precision='round_trip')
    intra.index=pd.to_datetime(intra.index,utc=True)
    features['intrahour']=pd.concat([features['eth'],intra.reindex(meta.index)],axis=1)
    masks=development_splits(meta)
    selection=masks['selection']
    if selection.sum()!=4416 or any(f.loc[selection].isna().any().any() for f in features.values()):
        raise ValueError('Cannot omit original validation hours')
    y=meta.actual_log_return.to_numpy()*10000
    raw_scale=np.maximum(base['base']['return_std_24'].to_numpy()*10000,1.)
    rows=[]
    with threadpool_limits(limits=2):
        for set_name,frame in features.items():
            for days in plan['train_days']:
                for transform in plan['transforms']:
                    scale=raw_scale if transform!='raw' else np.ones(len(y))
                    for recipe in models:
                        name=f'{set_name}__days{days}__{transform}__{recipe["name"]}'
                        folder=output/name
                        folder.mkdir()
                        predicted=pd.Series(np.nan,index=meta.index)
                        evidence=[]
                        print(f'Fitting six monthly models: {name}',flush=True)
                        for month in plan['months']:
                            start=pd.Timestamp(month+'-01',tz='UTC')
                            end=start+pd.DateOffset(months=1)
                            train=meta.target_open_time.ge(start-pd.Timedelta(days=days)) & meta.target_open_time.lt(start) & frame.notna().all(axis=1)
                            val=meta.target_open_time.ge(start) & meta.target_open_time.lt(end)
                            if train.sum()<1000 or meta.loc[train,'target_close_time'].max()>meta.loc[val,'cutoff_time'].min():
                                raise ValueError('Insufficient history or label crosses decision cutoff')
                            model=make_model(recipe)
                            weights=scale[train]/np.mean(scale[train])
                            model.fit(frame.loc[train],y[train]/scale[train],sample_weight=weights)
                            result=model.predict(frame.loc[val])*scale[val]/10000
                            predicted.loc[val]=result
                            path=folder/f'{month}.joblib'
                            joblib.dump(model,path)
                            np.testing.assert_array_equal(result,joblib.load(path).predict(frame.loc[val])*scale[val]/10000)
                            evidence.append(dict(month=month,train_n=int(train.sum()),validation_n=int(val.sum()),
                                last_train_label_close=meta.loc[train,'target_close_time'].max().isoformat(),
                                first_cutoff=meta.loc[val,'cutoff_time'].min().isoformat(),model_sha256=digest(path.read_bytes())))
                        if predicted.loc[selection].isna().any():
                            raise ValueError('Incomplete selection predictions')
                        saved=meta.loc[selection].copy()
                        saved['predicted_log_return']=predicted.loc[selection]
                        saved.to_csv(folder/'predictions.csv',index=False,float_format='%.17g')
                        seal(folder/'folds.json',evidence)
                        seal(folder/'schema.json',list(frame.columns))
                        for multiplier in plan['multipliers']:
                            summary=metric(meta.loc[selection,'actual_log_return'].to_numpy(),predicted.loc[selection].to_numpy()*multiplier)
                            rows.append(dict(name=name,multiplier=multiplier,metrics=summary))
                            print(f'  shrink={multiplier}: Relative MAE={summary["relative_mae"]:.6f}',flush=True)
    winner=min(rows,key=lambda r:r['metrics']['relative_mae'])
    seal(output/'report.json',dict(rows=rows,winner=winner,target_met=winner['metrics']['relative_mae']<=.97,
        monthly_model_fits=96,selection_rows_per_candidate=4416,test_2026_rows_used=0,reload_verified=True))
    print(f'WINNER {winner}',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,default=Path('data/models/hourly-rolling-research'))
    args=parser.parse_args()
    run(args.source,args.output_root)
