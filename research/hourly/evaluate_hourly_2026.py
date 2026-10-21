"""Score the already-frozen ensemble on 2026 through the latest closed hour. Never fit."""
from datetime import datetime,timezone
from pathlib import Path
import shutil,time
from uuid import uuid4
import joblib
import numpy as np
import pandas as pd
import requests
from pipeline.decision.hourly_future import seal,unseal,digest
from pipeline.decision.hourly_features import prepare_grid
from pipeline.decision.hourly_engineering import feature_sets
from pipeline.decision.hourly_cross_asset import build_cross_inputs
from pipeline.decision.hourly_calibrated import predict_ensemble
from research.hourly.research_hourly_mae import metric


def run():
    bundle=Path('data/models/hourly-calibration-research/f9e5fc24-d0d3-442b-9133-f743dc7d5b3d/selected_bundle').resolve()
    spec=unseal(bundle/'ensemble.json')
    hashes={m['path']:digest((bundle/m['path']).read_bytes()) for m in spec['members']}
    if any(hashes[m['path']]!=m['model_sha256'] for m in spec['members']): raise ValueError('Changed frozen member')
    out=Path('data/models/hourly-2026-evaluation')/str(uuid4());out.mkdir(parents=True)
    api='https://data-api.binance.vision';s=requests.Session()
    response=s.get(api+'/api/v3/time',timeout=25);response.raise_for_status();server=response.json()['serverTime']
    now=pd.Timestamp.now(tz='UTC')
    if abs(server-now.timestamp()*1000)>10000: raise ValueError('Exchange/local clock mismatch')
    end=pd.Timestamp(server,unit='ms',tz='UTC').floor('h');start=pd.Timestamp('2026-01-01',tz='UTC');raw_start=start-pd.Timedelta(hours=170)
    plan=dict(created_at=datetime.now(timezone.utc).isoformat(),model='Frozen two-member research ensemble',bundle=str(bundle),
        bundle_sha256=digest((bundle/'ensemble.json').read_bytes()),member_hashes=hashes,
        member_coefficients=[m['coefficient'] for m in spec['members']],api=api,server_time_ms=server,
        test_target_start=start.isoformat(),test_target_close_end_inclusive=end.isoformat(),raw_start=raw_start.isoformat(),
        baseline='zero-return',target='BTCUSDT next-hour log return',relative_mae_reference_target=.97,
        training=False,calibration=False,parameter_selection=False,live_promotion=False,scheduler=False,
        test_status='Retrospective 2026, previously viewed in EDA. Not untouched future holdout.',
        validation_status='2025 previously used for model selection; ensemble weights calibrated on Jan-Jun 2025.',
        max_requests=30,max_bytes=15*1024**2,max_seconds=300)
    seal(out/'plan.json',plan);shutil.copytree(bundle,out/'frozen_bundle');shutil.copy2(__file__,out/Path(__file__).name)
    print(f'RUN={out}',flush=True);print(f'Last closed target hour: {end-pd.Timedelta(hours=1)}',flush=True)
    source=out/'sources';source.mkdir();raw={};total=0;calls=0;began=time.monotonic();manifest=[]
    for asset in ('BTC','ETH'):
        frames=[]
        for chunk in pd.date_range(raw_start,end,freq='1000h',inclusive='left'):
            if time.monotonic()-began>300 or calls>=30: raise ValueError('Fetch quota exceeded')
            stop=min(chunk+pd.Timedelta(hours=1000),end)
            params=dict(symbol=asset+'USDT',interval='1h',startTime=int(chunk.timestamp()*1000),endTime=int(stop.timestamp()*1000)-1,limit=1000)
            r=s.get(api+'/api/v3/klines',params=params,timeout=25);calls+=1;r.raise_for_status();rows=r.json()
            if not isinstance(rows,list) or not rows: raise ValueError('Missing requested candles')
            frame=[]
            for row in rows:
                if len(row)!=12 or int(row[6])!=int(row[0])+3599999: raise ValueError('Invalid kline schema')
                t=pd.Timestamp(int(row[0]),unit='ms',tz='UTC')
                if t<chunk or t>=stop or t!=t.floor('h'): raise ValueError('Out-of-period kline')
                frame.append(dict(open_time=t,open_price=float(row[1]),high_price=float(row[2]),low_price=float(row[3]),close_price=float(row[4]),volume_quote=float(row[7]),trade_count=float(row[8])))
            f=source/f'{asset}_{chunk:%Y%m%d%H}.json';seal(f,dict(url=r.url,fetched_at=datetime.now(timezone.utc).isoformat(),rows=rows))
            total+=f.stat().st_size
            if total>plan['max_bytes']: raise ValueError('Byte quota exceeded')
            manifest.append(dict(path=str(f.relative_to(out)),sha256=digest(f.read_bytes())))
            frames.append(pd.DataFrame(frame));time.sleep(.15)
        frame=pd.concat(frames,ignore_index=True).sort_values('open_time')
        if frame.open_time.duplicated().any() or not prepare_grid(frame)[2].all(): raise ValueError('Missing/invalid raw candle')
        expected=pd.date_range(raw_start,end,freq='h',inclusive='left')
        if not pd.DatetimeIndex(frame.open_time).equals(expected): raise ValueError('Source gap: do not silently reduce test sample')
        frame.to_csv(out/f'{asset.lower()}_snapshot.csv',index=False,float_format='%.17g');raw[asset]=pd.read_csv(out/f'{asset.lower()}_snapshot.csv',float_precision='round_trip')
        raw[asset].open_time=pd.to_datetime(raw[asset].open_time,utc=True)
        print(f'{asset}: {len(frame)} complete raw candles',flush=True)
    seal(out/'sources.json',manifest)
    sets,meta,_=feature_sets(raw['BTC']);test=meta.target_open_time.ge(start)&meta.target_close_time.le(end)
    meta=meta.loc[test];expected=pd.date_range(start,end,freq='h',inclusive='left')
    if not pd.DatetimeIndex(meta.target_open_time).equals(expected): raise ValueError('Test timestamps not complete')
    compact=sets['compact'].reindex(meta.index);eth=build_cross_inputs(raw['BTC'],raw['ETH']).reindex(meta.index)
    inputs=dict(compact=compact,eth=pd.concat([compact,eth],axis=1));pred=np.zeros(len(meta))
    for member in spec['members']:
        model=joblib.load(out/'frozen_bundle'/member['path']);x=inputs[member['feature_set']]
        if list(x.columns)!=member['features'] or x.isna().any().any(): raise ValueError('Feature schema/missing error')
        pred+=member['coefficient']*model.predict(x,thread_count=2)/member['target_divisor']
    saved=meta.copy();saved['partition']='retrospective_test_2026';saved['predicted_log_return']=pred;saved['zero_log_return']=0.
    saved.to_csv(out/'predictions.csv',index=False,float_format='%.17g')
    # Independent 169-candle, label-free inference checks across the test period.
    for idx in (0,len(meta)//2,len(meta)-1):
        cutoff=meta.iloc[idx].cutoff_time
        context={a:d[d.open_time.ge(cutoff-pd.Timedelta(hours=169))&d.open_time.lt(cutoff)].copy() for a,d in raw.items()}
        replay=predict_ensemble(out/'frozen_bundle',context['BTC'],context['ETH'],cutoff)
        np.testing.assert_allclose(replay,pred[idx],rtol=1e-8,atol=1e-12)
    actual=saved.actual_log_return.to_numpy();metrics=metric(actual,pred)
    metrics.update(rmse=float(np.sqrt(np.mean((actual-pred)**2))),directional_accuracy_pct=float(np.mean(np.sign(actual)==np.sign(pred))*100))
    monthly=[]
    for month,part in saved.groupby(saved.target_open_time.dt.strftime('%Y-%m')):
        monthly.append(dict(month=month,**metric(part.actual_log_return.to_numpy(),part.predicted_log_return.to_numpy())))
    reloaded=pd.read_csv(out/'predictions.csv',float_precision='round_trip');check=metric(reloaded.actual_log_return.to_numpy(),reloaded.predicted_log_return.to_numpy())
    for k,v in check.items(): assert abs(metrics[k]-v)<1e-12
    for name,expected_hash in hashes.items(): assert digest((bundle/name).read_bytes())==expected_hash
    assert digest((bundle/'ensemble.json').read_bytes())==plan['bundle_sha256']
    for item in manifest: assert digest((out/item['path']).read_bytes())==item['sha256']
    report=dict(plan=plan,metrics=metrics,monthly=monthly,first_target_open=saved.target_open_time.iloc[0].isoformat(),
        last_target_open=saved.target_open_time.iloc[-1].isoformat(),last_target_close=end.isoformat(),
        expected_hours=len(expected),scored_hours=len(saved),coverage=1.,predictions_sha256=digest((out/'predictions.csv').read_bytes()),
        source_requests=calls,source_bytes=total,frozen_hashes_unchanged=True,label_free_replay_checks=3,metrics_recomputed=True,
        reaches_097=metrics['relative_mae']<=.97,no_fit_performed=True)
    seal(out/'report.json',report);print(report['metrics'],flush=True);print('DONE',out,flush=True)

if __name__=='__main__':run()
