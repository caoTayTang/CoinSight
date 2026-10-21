"""Four small CPU sequence models; select epochs on Jan-Jun, score fixed Jul-Dec."""
import argparse
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
import shutil
from uuid import uuid4

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader,TensorDataset

from pipeline.batch.binance_archive_format import parse_kline_csv,read_zip_csv
from pipeline.decision.hourly_features import build_dataset
from pipeline.decision.hourly_future import digest,seal,unseal
from pipeline.decision.hourly_sequence import make_network,sequence_inputs
from pipeline.decision.hourly_tuning import development_splits
from research.hourly.research_hourly_mae import metric


def predict(model,x,scale):
    model.eval()
    out=[]
    with torch.no_grad():
        for start in range(0,len(x),256):
            out.append(model(x[start:start+256]).numpy())
    return np.concatenate(out).astype(float)*scale


def run(source,root):
    source,root=Path(source).resolve(),Path(root).resolve()
    original=unseal(source/'plan.json')
    snapshot=source/'development_snapshot.csv'
    if digest(snapshot.read_bytes())!=original['source_snapshot_sha256']:
        raise ValueError('Source snapshot changed')
    output=root/str(uuid4())
    output.mkdir(parents=True,exist_ok=False)
    plan=dict(created_at=datetime.now(timezone.utc).isoformat(),source=str(source),
        snapshot_sha256=digest(snapshot.read_bytes()),goal_relative_mae=.97,
        models=['tcn','lstm'],assets=['btc','btc_eth'],seed=42,epochs_max=8,patience=3,batch_size=128,
        optimizer='AdamW lr=.001 weight_decay=.01; gradient norm <=1',device='cpu',threads=2,
        inputs='168 transitions from 169 closed raw candles; per-window causal normalization; 4 known time channels',
        target='Original BTC next-hour log-return, scaled by past window volatility floor 1bp',
        loss='Absolute error in raw-return units, normalized by mean train scale',
        train='2024',epoch_selection='Jan-Jun 2025 only',scoring='Jul-Dec 2025 all 4416 original hours',
        multipliers=[1.,.5],torch_version=str(torch.__version__),test_2026_rows_used=0,scheduler=False,live_promotion=False,
        caveat='Reused validation and expanded selection budget; not unseen evidence')
    seal(output/'plan.json',plan)
    project=Path(__file__).resolve().parents[2]
    shutil.copy2(Path(__file__),output/'research_hourly_sequence.py')
    shutil.copy2(project/'pipeline/decision/hourly_sequence.py',output/'hourly_sequence.py')
    print(f'RUN={output}',flush=True)
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    btc=pd.read_csv(snapshot,float_precision='round_trip')
    btc['open_time']=pd.to_datetime(btc.open_time,utc=True)
    if btc.open_time.ge(pd.Timestamp('2026-01-01',tz='UTC')).any():
        raise ValueError('Test data forbidden')
    cross=Path(original['cross_source'])
    eth=[]
    for item in unseal(source/'eth_sources.json'):
        path=cross/'eth_archives'/item['url'].rsplit('/',1)[-1]
        if digest(path.read_bytes())!=item['sha256']:
            raise ValueError('ETH archive changed')
        eth.append(pd.DataFrame(parse_kline_csv(read_zip_csv(path))))
    eth=pd.concat(eth,ignore_index=True)
    eth['open_time']=pd.to_datetime(eth.open_time,utc=True)
    _,meta,_=build_dataset(btc)
    meta=meta[meta.target_open_time.ge(pd.Timestamp('2024-01-01',tz='UTC'))]
    masks=development_splits(meta)
    train,stop,selection=(masks[k].to_numpy() for k in ('train','early_stop','selection'))
    val=stop|selection
    if train.sum()!=8784 or stop.sum()!=4344 or selection.sum()!=4416:
        raise ValueError('Original sample counts changed')
    rows=[]
    for asset in plan['assets']:
        x,scale=sequence_inputs(btc,eth,meta.input_open_time,asset=='btc_eth')
        # Inference and normalization must not need any future label or outside context.
        cutoff=meta.input_open_time.iloc[-1]
        bx=btc[btc.open_time.le(cutoff)].tail(169)
        ex=eth[eth.open_time.le(cutoff)].tail(169)
        last,last_scale=sequence_inputs(bx,ex,[cutoff],asset=='btc_eth')
        np.testing.assert_array_equal(last[0],x[-1])
        np.testing.assert_array_equal(last_scale,scale[-1:])
        xt=torch.from_numpy(x)
        yt=torch.from_numpy((meta.actual_log_return.to_numpy()/scale).astype('float32'))
        st=torch.from_numpy(scale)
        train_scale=float(scale[train].mean())
        for architecture in plan['models']:
            torch.manual_seed(42)
            name=asset+'__'+architecture
            folder=output/name
            folder.mkdir()
            model=make_network(x.shape[-1],architecture).cpu()
            optimizer=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.01)
            generator=torch.Generator().manual_seed(42)
            loader=DataLoader(TensorDataset(xt[train],yt[train],st[train]),batch_size=128,shuffle=True,
                              num_workers=0,generator=generator)
            best_score=1.
            best_epoch=0
            best_state=deepcopy(model.state_dict())
            history=[]
            print(f'Training {name}, channels={x.shape[-1]}, max 8 epochs',flush=True)
            for epoch in range(1,9):
                model.train()
                for batch,target,scales in loader:
                    optimizer.zero_grad()
                    loss=(torch.abs(model(batch)-target)*scales/train_scale).mean()
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(),1.)
                    optimizer.step()
                predictions=predict(model,xt[stop],scale[stop])
                score=metric(meta.loc[stop,'actual_log_return'].to_numpy(),predictions)['relative_mae']
                history.append(dict(epoch=epoch,early_stop_relative_mae=score))
                print(f'  epoch={epoch} Jan-Jun Relative MAE={score:.6f}',flush=True)
                if score<best_score:
                    best_score,best_epoch,best_state=score,epoch,deepcopy(model.state_dict())
                if epoch-best_epoch>=3:
                    break
            model.load_state_dict(best_state)
            torch.save(best_state,folder/'weights.pt')
            seal(folder/'history.json',history)
            predicted=predict(model,xt[val],scale[val])
            reload=make_network(x.shape[-1],architecture)
            reload.load_state_dict(torch.load(folder/'weights.pt',weights_only=True,map_location='cpu'))
            np.testing.assert_array_equal(predicted,predict(reload,xt[val],scale[val]))
            saved=meta.loc[val].copy()
            saved['partition']=np.where(stop[val],'early_stop','selection')
            saved['predicted_log_return']=predicted
            saved.to_csv(folder/'predictions.csv',index=False,float_format='%.17g')
            for multiplier in plan['multipliers']:
                metrics={}
                for part in ('early_stop','selection'):
                    mask=saved.partition.eq(part)
                    metrics[part]=metric(saved.loc[mask,'actual_log_return'].to_numpy(),predicted[mask]*multiplier)
                rows.append(dict(name=name,multiplier=multiplier,best_epoch=best_epoch,metrics=metrics,
                                 model_sha256=digest((folder/'weights.pt').read_bytes())))
                print(f'  selected epoch={best_epoch} shrink={multiplier}: selection Relative MAE={metrics["selection"]["relative_mae"]:.6f}',flush=True)
    winner=min(rows,key=lambda r:r['metrics']['selection']['relative_mae'])
    seal(output/'report.json',dict(rows=rows,winner=winner,target_met=winner['metrics']['selection']['relative_mae']<=.97,
        reload_verified=True,context_169_verified=True,test_2026_rows_used=0))
    print(f'WINNER {winner}',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,default=Path('data/models/hourly-sequence-research'))
    args=parser.parse_args()
    run(args.source,args.output_root)
