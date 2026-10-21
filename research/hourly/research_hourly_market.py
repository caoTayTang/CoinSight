"""Fixed basket-information and multi-asset auxiliary-training experiments."""
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
from pipeline.decision.hourly_market import MARKET_SYMBOLS,market_inputs,load_market_assets
from pipeline.decision.hourly_tuning import development_splits
from research.hourly.research_hourly_mae import make_model,metric,recipes
from research.hourly.research_hourly_transfer import normalized_features


def run(source,history,cache,root):
    source,history,cache,root=(Path(p).resolve() for p in (source,history,cache,root))
    old=unseal(source/'plan.json');snapshot=source/'development_snapshot.csv'
    if digest(snapshot.read_bytes())!=old['source_snapshot_sha256']:
        raise ValueError('BTC snapshot changed')
    output=root/str(uuid4());output.mkdir(parents=True,exist_ok=False)
    models=[r for r in recipes() if r['family'] in ('cat','hist','xgb')]
    plan=dict(created_at=datetime.now(timezone.utc).isoformat(),source=str(source),history_source=str(history),
        goal_relative_mae=.97,snapshot_sha256=digest(snapshot.read_bytes()),new_assets=list(MARKET_SYMBOLS),
        train='2023-2024 only',diagnostic='Jan-Jun 2025',selection='BTC Jul-Dec 2025 all original 4416 hours',
        feature_sets=['compact','eth','basket'],pool_sets=['btc_only','shared_equal','shared_btc50','indicator_btc50'],
        pool_weight_policy='shared_equal: 1/8 total weight per asset; btc50: BTC 1/2, each of seven others 1/14',
        recipes=models,multipliers=[1.,.5],basket='Seven other closed asset contexts, plus equal-weight return/breadth/dispersion',
        basket_missing_policy='Native missing handling; require at least three observed assets for aggregate; retain every target',
        target_normalization='Auxiliary training uses past std24 floor 1bp; activity offsets fit on train per asset only',
        test_2026_rows_used=0,scheduler=False,live_promotion=False,
        caveat='More search on previously viewed selection; no claim of unseen validation or live availability')
    seal(output/'plan.json',plan)
    project=Path(__file__).resolve().parents[2]
    shutil.copy2(Path(__file__),output/'research_hourly_market.py')
    shutil.copy2(project/'pipeline/decision/hourly_market.py',output/'hourly_market.py')
    print(f'RUN={output}',flush=True)
    raw=load_market_assets(output,cache)
    btc=pd.read_csv(snapshot,float_precision='round_trip');btc.open_time=pd.to_datetime(btc.open_time,utc=True)
    eth=[]
    for item in unseal(history/'eth_sources.json'):
        path=history/item['path']
        if digest(path.read_bytes())!=item['sha256']:
            raise ValueError('ETH archive changed')
        if '-2020-' not in path.name and '-2021-' not in path.name:
            eth.append(pd.DataFrame(parse_kline_csv(read_zip_csv(path))))
    eth=pd.concat(eth,ignore_index=True);eth.open_time=pd.to_datetime(eth.open_time,utc=True)
    raw['ETH']=eth
    for frame in [btc,*raw.values()]:
        if frame.open_time.ge(pd.Timestamp('2026-01-01',tz='UTC')).any():
            raise ValueError('Test candle forbidden')
    base,bm,_=feature_sets(btc)
    market=market_inputs(btc,raw)
    cutoff=pd.Timestamp('2025-06-01',tz='UTC')
    pd.testing.assert_frame_equal(market.loc[:cutoff],market_inputs(btc[btc.open_time.le(cutoff)],
        {symbol:frame[frame.open_time.le(cutoff)] for symbol,frame in raw.items()}))
    market.to_csv(output/'market_features.csv',float_format='%.17g')
    masks=development_splits(bm)
    val=(masks['early_stop']|masks['selection']).to_numpy()
    train=(masks['train']&bm.target_open_time.ge(pd.Timestamp('2023-01-01',tz='UTC'))).to_numpy()
    if train.sum()!=17374 or val.sum()!=8760 or masks['selection'].sum()!=4416:
        raise ValueError('Original BTC samples changed')
    frames={'compact':base['compact'],
            'eth':pd.concat([base['compact'],build_cross_inputs(btc,eth).reindex(bm.index)],axis=1),
            'basket':pd.concat([base['compact'],market.reindex(bm.index)],axis=1)}
    coverage={part:dict(min_known_assets=int(market.reindex(bm.index).loc[mask,'basket_known_assets'].min()),
        all_features_complete_pct=float(frames['basket'].loc[mask].notna().all(axis=1).mean()*100))
        for part,mask in [('train',train),('diagnostic',masks['early_stop']),('selection',masks['selection'])]}
    seal(output/'source_coverage.json',coverage)
    rows=[]
    def fit_and_score(name,x,y,weights,xval,prediction_scale):
        folder=output/name;folder.mkdir()
        recipe=next(r for r in models if name.endswith('__'+r['name']))
        print(f'Fitting {name}: n={len(y)}, features={x.shape[1]}',flush=True)
        model=make_model(recipe)
        if weights is None:
            model.fit(x,y)
        else:
            model.fit(x,y,sample_weight=weights)
        predicted=model.predict(xval)*prediction_scale
        joblib.dump(model,folder/'model.joblib')
        np.testing.assert_array_equal(predicted,joblib.load(folder/'model.joblib').predict(xval)*prediction_scale)
        saved=bm.loc[val].copy();saved['partition']=np.where(masks['early_stop'].loc[val],'early_stop','selection')
        saved['predicted_log_return']=predicted
        saved.to_csv(folder/'predictions.csv',index=False,float_format='%.17g')
        seal(folder/'schema.json',list(x.columns))
        for multiplier in plan['multipliers']:
            metrics={}
            for part in ('early_stop','selection'):
                selected=saved.partition.eq(part)
                metrics[part]=metric(saved.loc[selected,'actual_log_return'].to_numpy(),predicted[selected]*multiplier)
            rows.append(dict(name=name,multiplier=multiplier,metrics=metrics,train_n=len(y),
                model_sha256=digest((folder/'model.joblib').read_bytes())))
            print(f'  shrink={multiplier}: Relative MAE={metrics["selection"]["relative_mae"]:.6f}',flush=True)
    with threadpool_limits(limits=2):
        for name,frame in frames.items():
            for recipe in models:
                fit_and_score('features_'+name+'__'+recipe['name'],frame.loc[train],
                    bm.loc[train,'actual_log_return']*10000,None,frame.loc[val],.0001)
        assets={}
        for symbol,frame in [('BTC',btc),*sorted(raw.items())]:
            sets,meta,_=feature_sets(frame)
            tr=meta.target_open_time.ge(pd.Timestamp('2023-01-01',tz='UTC'))&meta.target_open_time.lt(pd.Timestamp('2025-01-01',tz='UTC'))
            normalized,scale,offsets=normalized_features(sets['compact'],tr)
            assets[symbol]=dict(features=normalized,scale=scale,train=tr.to_numpy(),
                target=meta.actual_log_return.to_numpy()/scale,weights=scale/scale[tr].mean())
            seal(output/(symbol+'_normalization.json'),dict(offsets=offsets,train_n=int(tr.sum()),
                last_train_label_close=meta.loc[tr,'target_close_time'].max().isoformat()))
        symbols=sorted(assets)
        for pool in plan['pool_sets']:
            xx=[];yy=[];ww=[]
            for symbol in (['BTC'] if pool=='btc_only' else symbols):
                asset=assets[symbol];tr=asset['train']
                frame=asset['features'].loc[tr].copy()
                if pool=='indicator_btc50':
                    for name in symbols:
                        frame['asset_'+name]=float(name==symbol)
                weight=asset['weights'][tr].copy()
                fraction=1. if pool=='btc_only' else (1/len(symbols) if pool=='shared_equal' else (.5 if symbol=='BTC' else .5/(len(symbols)-1)))
                weight*=fraction/weight.sum()
                xx.append(frame);yy.append(asset['target'][tr]);ww.append(weight)
            x=pd.concat(xx,ignore_index=True);y=np.concatenate(yy);weights=np.concatenate(ww)
            weights*=len(weights)/weights.sum()
            xval=assets['BTC']['features'].loc[val].copy()
            if pool=='indicator_btc50':
                for name in symbols:
                    xval['asset_'+name]=float(name=='BTC')
            for recipe in models:
                fit_and_score('pool_'+pool+'__'+recipe['name'],x,y,weights,xval,assets['BTC']['scale'][val])
    winner=min(rows,key=lambda r:r['metrics']['selection']['relative_mae'])
    seal(output/'report.json',dict(rows=rows,winner=winner,target_met=winner['metrics']['selection']['relative_mae']<=.97,
        reload_verified=True,causal_prefix_verified=True,test_2026_rows_used=0))
    print(f'WINNER {winner}',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--history',type=Path,required=True)
    parser.add_argument('--cache',type=Path,default=Path('data/models/hourly-market-sources'))
    parser.add_argument('--output-root',type=Path,default=Path('data/models/hourly-market-research'))
    args=parser.parse_args()
    run(args.source,args.history,args.cache,args.output_root)
