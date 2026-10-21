"""Bounded, rate-limited historical GDELT volume collection; no training or scheduling."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import time
from uuid import uuid4

import pandas as pd
import requests

from pipeline.decision.hourly_future import digest, seal, unseal

API='https://api.gdeltproject.org/api/v2/doc/doc'


def collect(root):
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    out=root/str(uuid4());out.mkdir()
    starts=pd.date_range('2023-12-18','2026-01-01',freq='7D',tz='UTC')
    stop=pd.Timestamp('2026-01-01',tz='UTC')
    plan=dict(created_at=datetime.now(timezone.utc).isoformat(),api=API,query='bitcoin',
              mode='timelinevolraw',smoothing=0,starts=[s.isoformat() for s in starts],
              end_exclusive=stop.isoformat(),request_spacing_seconds=6,timeout_seconds=35,
              max_bytes=20*1024**2,max_requests=120,max_seconds=1100,
              downstream_train='2024 only',downstream_diagnostic='Jan-Jun 2025',
              downstream_selection='All original 4416 BTC Jul-Dec 2025 hours',
              proposed_availability='hour bucket start + 1h completion + 2h delay; sensitivity +24h',
              missing_policy='Missing bins remain missing, never infer zero counts',
              caveat='Retrieved historical index, not point-in-time archive; no live promotion',
              scheduler=False)
    seal(out/'plan.json',plan)
    entries=[];frames=[];last=0.;total=0;began=time.monotonic()
    print(f'RUN={out}',flush=True)
    session=requests.Session()
    try:
        for i,start in enumerate(starts):
            if time.monotonic()-began>plan['max_seconds'] or i>=plan['max_requests']:
                raise RuntimeError('Collection resource quota reached')
            end=min(start+pd.Timedelta(days=7),stop)
            query_start=min(start,end-pd.Timedelta(days=7))
            params=dict(query='bitcoin',mode='timelinevolraw',format='json',timelinesmooth=0,
                        startdatetime=query_start.strftime('%Y%m%d%H%M%S'),enddatetime=end.strftime('%Y%m%d%H%M%S'))
            cache=root/f'{start:%Y%m%d}_{end:%Y%m%d}.json'
            if cache.exists():
                record=unseal(cache);raw=record['response'];url=record['url'];fetched=record['fetched_at']
                if record['params']!=params: raise ValueError('Cached query mismatch')
            else:
                time.sleep(max(0.,6-(time.monotonic()-last)))
                last=time.monotonic()
                response=session.get(API,params=params,timeout=35)
                if not response.ok:
                    (out/'http_failure.txt').write_text(response.text[:4000])
                response.raise_for_status()
                if len(response.content)>1024**2: raise ValueError('Oversized weekly response')
                raw=response.json();url=response.url;fetched=datetime.now(timezone.utc).isoformat()
                seal(cache,dict(params=params,url=url,fetched_at=fetched,response=raw))
            if raw.get('query_details',{}).get('date_resolution') not in ('hour','15m'):
                raise ValueError('Unexpected timeline resolution')
            series=raw.get('timeline',[])
            if len(series)!=1 or series[0].get('series')!='Article Count': raise ValueError('Unexpected series')
            data=pd.DataFrame(series[0]['data'])
            if not {'date','value','norm'}<=set(data): raise ValueError('Missing count or denominator')
            data['bucket_start']=pd.to_datetime(data.date,format='%Y%m%dT%H%M%SZ',utc=True)
            if data.bucket_start.duplicated().any() or not data.bucket_start.between(query_start,end).all():
                raise ValueError('Timeline outside requested period')
            # Weekly requests are hourly. Last short request can have 15m bins: reject rather than mix.
            if raw['query_details']['date_resolution']!='hour': raise ValueError('Need complete weekly hour bins')
            data=data[data.bucket_start.ge(start)&data.bucket_start.lt(end)].copy()
            if not ((data.value>=0)&(data.norm>0)&(data.value<=data.norm)).all(): raise ValueError('Invalid counts')
            frames.append(data[['bucket_start','value','norm']])
            total+=cache.stat().st_size
            if total>plan['max_bytes']: raise RuntimeError('Byte quota reached')
            entries.append(dict(path=str(cache),sha256=digest(cache.read_bytes()),url=url,fetched_at=fetched))
            print(f'{i+1}/{len(starts)} {start:%Y-%m-%d}: {len(data)} bins',flush=True)
        merged=pd.concat(frames,ignore_index=True).sort_values('bucket_start')
        if merged.bucket_start.duplicated().any(): raise ValueError('Overlapping source bins')
        merged.to_csv(out/'hourly_counts.csv',index=False)
        seal(out/'sources.json',entries)
        seal(out/'report.json',dict(complete=True,rows=len(merged),source_bytes=total,
                                   csv_sha256=digest((out/'hourly_counts.csv').read_bytes())))
    except Exception as exc:
        seal(out/'failure.json',dict(error=type(exc).__name__,detail=str(exc),completed_weeks=len(entries)))
        raise
    return out


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-root',type=Path,default=Path('data/models/hourly-news-sources'))
    collect(p.parse_args().output_root)
