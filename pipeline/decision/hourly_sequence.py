"""Bounded 169-candle contexts for direct sequence forecasts; labels are never inputs."""
import numpy as np
import pandas as pd

from pipeline.decision.hourly_features import prepare_grid


def sequence_asset_weights(scales,fraction,total_rows):
    """Give an auxiliary asset its declared total loss weight, preserving causal risk."""
    scales=np.asarray(scales,dtype=float)
    if len(scales)==0 or not np.isfinite(scales).all() or (scales<=0).any():
        raise ValueError('Invalid causal volatility scale')
    return scales/scales.sum()*fraction*total_rows


def sequence_inputs(btc,eth,ends,include_eth):
    _,b,bvalid=prepare_grid(btc)
    ends=pd.DatetimeIndex(pd.to_datetime(ends,utc=True))
    locations=b.index.get_indexer(ends)
    if len(ends)==0 or (locations<168).any():
        raise ValueError('Need 169 closed BTC candles for every context')
    if not bvalid.rolling(169,min_periods=169).sum().eq(169).reindex(ends).all():
        raise ValueError('BTC context has gaps or invalid candles')
    channels=[]
    btc_scale=None
    assets=[b]
    if include_eth:
        _,e,evalid=prepare_grid(eth.drop(columns=['symbol'],errors='ignore'))
        e=e.reindex(b.index)
        evalid=evalid.reindex(b.index,fill_value=False)
        if not evalid.rolling(169,min_periods=169).sum().eq(169).reindex(ends).all():
            raise ValueError('ETH context has gaps or invalid candles')
        assets.append(e)
    for asset in assets:
        returns=np.log(asset.close_price/asset.close_price.shift(1)).to_numpy()
        body=np.log(asset.close_price/asset.open_price).to_numpy()
        ranges=np.log(asset.high_price/asset.low_price).to_numpy()
        spread=asset.high_price-asset.low_price
        position=((asset.close_price-asset.low_price)/spread.where(spread.ne(0))).where(spread.ne(0),.5).to_numpy()-.5
        raw=np.column_stack([returns,body,ranges,position,np.log1p(asset.volume_quote),np.log1p(asset.trade_count)])
        window=np.lib.stride_tricks.sliding_window_view(raw,168,axis=0)
        window=np.moveaxis(window,-1,1)[locations-167].copy()
        scale=np.maximum(window[:,:,0].std(axis=1,ddof=0),.0001)
        if btc_scale is None:
            btc_scale=scale
        window[:,:,:3]/=scale[:,None,None]
        for column in (4,5):
            values=window[:,:,column]
            window[:,:,column]=(values-values.mean(axis=1,keepdims=True))/np.maximum(values.std(axis=1,keepdims=True),.1)
        channels.append(window)
    clock=np.column_stack([np.sin(2*np.pi*b.index.hour/24),np.cos(2*np.pi*b.index.hour/24),
                           np.sin(2*np.pi*b.index.dayofweek/7),np.cos(2*np.pi*b.index.dayofweek/7)])
    time_window=np.moveaxis(np.lib.stride_tricks.sliding_window_view(clock,168,axis=0),-1,1)[locations-167]
    array=np.concatenate([*channels,time_window],axis=2)
    if not np.isfinite(array).all():
        raise ValueError('Non-finite sequence inputs')
    return np.clip(array,-10,10).astype('float32'),btc_scale.astype('float32')


def make_network(channels,architecture):
    import torch
    from torch import nn
    if architecture=='lstm':
        class SequenceLSTM(nn.Module):
            def __init__(self):
                super().__init__()
                self.recurrent=nn.LSTM(channels,16,batch_first=True)
                self.head=nn.Linear(16,1)
                nn.init.zeros_(self.head.weight)
                nn.init.zeros_(self.head.bias)
            def forward(self,x):
                _,(hidden,_)=self.recurrent(x)
                return self.head(hidden[-1]).squeeze(-1)
        return SequenceLSTM()
    if architecture!='tcn':
        raise ValueError('Unknown sequence architecture')
    class SequenceTCN(nn.Module):
        def __init__(self):
            super().__init__()
            self.projection=nn.Conv1d(channels,8,1)
            self.blocks=nn.ModuleList([nn.Conv1d(8,8,3,dilation=d,padding=2*d) for d in (1,2,4,8,16,32)])
            self.activation=nn.GELU()
            self.head=nn.Linear(8,1)
            nn.init.zeros_(self.head.weight)
            nn.init.zeros_(self.head.bias)
        def forward(self,x):
            z=self.projection(x.transpose(1,2))
            for convolution in self.blocks:
                z=z+self.activation(convolution(z)[:,:,:z.shape[-1]])
            return self.head(z[:,:,-1]).squeeze(-1)
    return SequenceTCN()
