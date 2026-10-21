"""Small shared sequence learners with auxiliary asset labels; BTC-only scoring."""
import argparse
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
import shutil
import time
from uuid import uuid4

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader,TensorDataset

from pipeline.batch.binance_archive_format import parse_kline_csv,read_zip_csv
from pipeline.decision.hourly_features import build_dataset
from pipeline.decision.hourly_future import digest,seal,unseal
from pipeline.decision.hourly_sequence import make_network,sequence_inputs,sequence_asset_weights
from pipeline.decision.hourly_tuning import development_splits
from research.hourly.research_hourly_mae import metric
from research.hourly.research_hourly_sequence import predict


def run(source,history,market,root):
    source,history,market,root=(Path(p).resolve() for p in (source,history,market,root))
    old=unseal(source/'plan.json');snapshot=source/'development_snapshot.csv'
    if digest(snapshot.read_bytes())!=old['source_snapshot_sha256']:
        raise ValueError('BTC snapshot changed')
    output=root/str(uuid4());output.mkdir(parents=True,exist_ok=False)
    plan=dict(created_at=datetime.now(timezone.utc).isoformat(),source=str(source),history_source=str(history),
        market_source=str(market),goal_relative_mae=.97,snapshot_sha256=digest(snapshot.read_bytes()),
        architectures=['tcn','lstm'],pools=['btc_only','eight_assets_btc50'],train='2023-2024 only',
        epoch_selection='BTC Jan-Jun 2025 only',selection='All original BTC Jul-Dec 2025 4416 hours',
        inputs='169 same-asset closed candles -> 168 transitions, 10 channels; causal context normalization',
        target='Normalized next-hour return, invert using causal BTC volatility for scoring',
        pool_loss='BTC 50% total weight, remaining seven assets 50%; raw MAE within asset normalized by asset mean volatility',
        seed=42,batch_size=256,max_epochs=6,patience=3,seconds_per_model_limit=180,
        optimizer='AdamW lr=.001 weight_decay=.01, gradient norm <=1',device='cpu',threads=2,
        memory_map_limit_bytes=int(1.5*1024**3),multipliers=[1.,.5],test_2026_rows_used=0,
        scheduler=False,live_promotion=False,torch_version=str(torch.__version__),
        caveat='Auxiliary targets correlated across assets; repeated selection, not unseen evaluation')
    seal(output/'plan.json',plan)
    shutil.copy2(Path(__file__),output/'research_hourly_pooled_sequence.py')
    project=Path(__file__).resolve().parents[2]
    shutil.copy2(project/'pipeline/decision/hourly_sequence.py',output/'hourly_sequence.py')
    print(f'RUN={output}',flush=True)
    torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.use_deterministic_algorithms(True)
    btc=pd.read_csv(snapshot,float_precision='round_trip');btc.open_time=pd.to_datetime(btc.open_time,utc=True)
    raw={'BTC':btc}
    eth=[]
    for entry in unseal(history/'eth_sources.json'):
        path=history/entry['path']
        if digest(path.read_bytes())!=entry['sha256']: raise ValueError('ETH archive changed')
        eth.append(pd.DataFrame(parse_kline_csv(read_zip_csv(path))))
    raw['ETH']=pd.concat(eth,ignore_index=True)
    groups={}
    for entry in unseal(market/'market_sources.json'):
        path=Path(entry['path'])
        if digest(path.read_bytes())!=entry['sha256']: raise ValueError('Market archive changed')
        groups.setdefault(entry['symbol'],[]).append(pd.DataFrame(parse_kline_csv(read_zip_csv(path))))
    raw.update({name:pd.concat(parts,ignore_index=True) for name,parts in groups.items()})
    info={}
    symbols=['BTC',*sorted(name for name in raw if name!='BTC')]
    for name in symbols:
        frame=raw[name]
        frame['open_time']=pd.to_datetime(frame.open_time,utc=True)
        if frame.open_time.ge(pd.Timestamp('2026-01-01',tz='UTC')).any(): raise ValueError('Test candle forbidden')
        if name!='BTC': frame=frame[frame.open_time.lt(pd.Timestamp('2025-01-01',tz='UTC'))].copy()
        _,meta,_=build_dataset(frame)
        train=meta.target_open_time.ge(pd.Timestamp('2023-01-01',tz='UTC'))&meta.target_open_time.lt(pd.Timestamp('2025-01-01',tz='UTC'))
        info[name]=dict(raw=frame,meta=meta,train=train.to_numpy(),n=int(train.sum()))
    if len(symbols)!=8 or info['BTC']['n']!=17374: raise ValueError('Unexpected pooled training universe')
    total=sum(item['n'] for item in info.values())
    size=total*168*10*4
    if size>plan['memory_map_limit_bytes']: raise ValueError('Sequence data exceed memory-map quota')
    x=np.lib.format.open_memmap(output/'train_sequences.npy',mode='w+',dtype='float32',shape=(total,168,10))
    y=np.empty(total,dtype='float32');weights=np.empty(total,dtype='float32')
    offset=0;provenance=[]
    for name in symbols:
        item=info[name];meta=item['meta'];train=item['train'];n=item['n']
        values,scale=sequence_inputs(item['raw'],item['raw'],meta.loc[train,'input_open_time'],False)
        x[offset:offset+n]=values
        y[offset:offset+n]=(meta.loc[train,'actual_log_return'].to_numpy()/scale).astype('float32')
        fraction=.5 if name=='BTC' else .5/(len(symbols)-1)
        weights[offset:offset+n]=sequence_asset_weights(scale,fraction,total).astype('float32')
        provenance.append(dict(asset=name,n=n,fraction=fraction,last_label_close=meta.loc[train,'target_close_time'].max().isoformat()))
        offset+=n
        del values,scale
        print(f'Prepared {name}: {n} train contexts',flush=True)
    x.flush();seal(output/'training_assets.json',provenance)
    meta=info['BTC']['meta'];masks=development_splits(meta)
    stop=masks['early_stop'].to_numpy();selection=masks['selection'].to_numpy();val=stop|selection
    if stop.sum()!=4344 or selection.sum()!=4416: raise ValueError('Original BTC validation changed')
    xv,sv=sequence_inputs(btc,btc,meta.loc[val,'input_open_time'],False)
    vx=torch.from_numpy(xv);vs=sv;actual=meta.loc[val,'actual_log_return'].to_numpy()
    diagnostic=stop[val]
    train_x=torch.from_numpy(x);train_y=torch.from_numpy(y);train_w=torch.from_numpy(weights)
    rows=[]
    for pool in plan['pools']:
        count=info['BTC']['n'] if pool=='btc_only' else total
        normalization=float(train_w[:count].mean())
        for architecture in plan['architectures']:
            torch.manual_seed(42)
            name=pool+'__'+architecture;folder=output/name;folder.mkdir()
            model=make_network(10,architecture).cpu()
            optimizer=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.01)
            loader=DataLoader(TensorDataset(train_x[:count],train_y[:count],train_w[:count]),batch_size=256,
                shuffle=True,num_workers=0,generator=torch.Generator().manual_seed(42))
            best=1.;epoch_best=0;state=deepcopy(model.state_dict());curve=[];started=time.monotonic()
            print(f'Training {name}, n={count}',flush=True)
            for epoch in range(1,7):
                model.train()
                for batch,target,weight in loader:
                    optimizer.zero_grad()
                    loss=(torch.abs(model(batch)-target)*weight/normalization).mean()
                    loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1.);optimizer.step()
                pred=predict(model,vx[diagnostic],vs[diagnostic])
                score=metric(actual[diagnostic],pred)['relative_mae']
                curve.append(dict(epoch=epoch,diagnostic_relative_mae=score,elapsed_seconds=time.monotonic()-started))
                print(f'  epoch={epoch} Jan-Jun Relative MAE={score:.6f}',flush=True)
                if score<best: best,epoch_best,state=score,epoch,deepcopy(model.state_dict())
                if epoch-epoch_best>=3 or time.monotonic()-started>=180: break
            model.load_state_dict(state);torch.save(state,folder/'weights.pt');seal(folder/'history.json',curve)
            prediction=predict(model,vx,vs)
            reloaded=make_network(10,architecture)
            reloaded.load_state_dict(torch.load(folder/'weights.pt',weights_only=True,map_location='cpu'))
            np.testing.assert_array_equal(prediction,predict(reloaded,vx,vs))
            saved=meta.loc[val].copy();saved['partition']=np.where(diagnostic,'early_stop','selection')
            saved['predicted_log_return']=prediction;saved.to_csv(folder/'predictions.csv',index=False,float_format='%.17g')
            for multiplier in plan['multipliers']:
                metrics={}
                for part in ('early_stop','selection'):
                    mask=saved.partition.eq(part)
                    metrics[part]=metric(saved.loc[mask,'actual_log_return'].to_numpy(),prediction[mask]*multiplier)
                rows.append(dict(name=name,multiplier=multiplier,best_epoch=epoch_best,metrics=metrics,train_n=count,
                    model_sha256=digest((folder/'weights.pt').read_bytes())))
                print(f'  shrink={multiplier}: selection Relative MAE={metrics["selection"]["relative_mae"]:.6f}',flush=True)
    winner=min(rows,key=lambda r:r['metrics']['selection']['relative_mae'])
    seal(output/'report.json',dict(rows=rows,winner=winner,training_contexts=total,memory_map_bytes=size,
        target_met=winner['metrics']['selection']['relative_mae']<=.97,reload_verified=True,test_2026_rows_used=0))
    print(f'WINNER {winner}',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--history',type=Path,required=True)
    parser.add_argument('--market',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,default=Path('data/models/hourly-pooled-sequence-research'))
    args=parser.parse_args()
    run(args.source,args.history,args.market,args.output_root)
