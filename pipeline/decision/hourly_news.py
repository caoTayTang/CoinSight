"""Causal, delayed features from historical hourly news count aggregates.

Index retrieval is retrospective: a configured delay is an assumption, not proof
of historical publication availability or protection against index revisions.
"""
import numpy as np
import pandas as pd


def news_inputs(counts, cutoffs, delay_hours=3):
    if delay_hours < 3:
        raise ValueError('Need completed hour plus at least two hours delay')
    frame=counts.copy()
    frame['bucket_start']=pd.to_datetime(frame.bucket_start,utc=True)
    if frame.bucket_start.duplicated().any():
        raise ValueError('Duplicate news buckets')
    if not frame.bucket_start.eq(frame.bucket_start.dt.floor('h')).all():
        raise ValueError('Need hourly buckets')
    frame=frame.set_index('bucket_start').sort_index()
    if frame.empty:
        raise ValueError('No source news buckets')
    if not ((frame.value>=0)&(frame.norm>0)&(frame.value<=frame.norm)).all():
        raise ValueError('Invalid count or normalization')
    frame=frame.reindex(pd.date_range(frame.index.min(),frame.index.max(),freq='h'))
    value=frame.value.astype(float);share=value/frame.norm
    features=pd.DataFrame(index=frame.index)
    features['news_log_count']=np.log1p(value)
    features['news_share']=share
    features['news_log_total']=np.log1p(frame.norm)
    for hours in (6,24,168):
        # No zero fill: mean and coverage describe only observed bins.
        features[f'news_share_mean{hours}']=share.rolling(hours,min_periods=max(1,hours*3//4)).mean()
        features[f'news_coverage{hours}']=share.notna().astype(float).rolling(hours,min_periods=hours).mean()
    features['news_share_change24']=share-share.shift(24)
    features.index=features.index+pd.Timedelta(hours=delay_hours)
    cutoff=pd.DatetimeIndex(cutoffs)
    if cutoff.tz is None:
        raise ValueError('Need timezone-aware forecast cutoffs')
    left=pd.DataFrame({'cutoff':cutoff,'position':np.arange(len(cutoff))}).sort_values('cutoff')
    right=features.rename_axis('available_at').reset_index()
    merged=pd.merge_asof(left,right,left_on='cutoff',right_on='available_at',direction='backward',
                         tolerance=pd.Timedelta(minutes=59))
    result=merged.sort_values('position')[list(features.columns)]
    result.index=getattr(cutoffs,'index',pd.RangeIndex(len(cutoff)))
    return result
