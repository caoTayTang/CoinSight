"""Frozen, local prospective BTC hourly experiment; no training or live promotion."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

import numpy as np
import pandas as pd


HOUR = 3_600_000
API = 'https://data-api.binance.vision'
PACKAGES = ('numpy', 'pandas', 'xgboost', 'scikit-learn', 'scipy', 'pyyaml')


def predict_candidate(*args, **kwargs):
    # Training/reporting dependencies are loaded only by the prospective runner.
    from pipeline.decision.hourly_tuning import predict_candidate as implementation
    return implementation(*args, **kwargs)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def seal(path, payload):
    """Publish complete records atomically, exclusively; never overwrite a record."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = canonical({'payload': payload, 'sha256': digest(canonical(payload))})
    fd, temporary = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o444)
        os.link(temporary, path)  # Fails atomically if this target already exists.
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.unlink(temporary)


def unseal(path):
    record = json.loads(Path(path).read_text())
    if digest(canonical(record['payload'])) != record['sha256']:
        raise ValueError(f'Record digest mismatch: {path}')
    return record['payload']


def get_json(base, endpoint, **query):
    request = Request(f'{base}{endpoint}?{urlencode(query)}', headers={'User-Agent': 'CoinSight-prospective/1'})
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def clock(base):
    before = time.time()*1000
    stamp = int(get_json(base, '/api/v3/time')['serverTime'])
    after = time.time()*1000
    if not before-5000 <= stamp <= after+5000 or after-before > 10000:
        raise ValueError('Exchange/local clock disagreement or excessive latency')
    return stamp


def klines(base, start, count):
    rows = get_json(base, '/api/v3/klines', symbol='BTCUSDT', interval='1h',
                    startTime=start, endTime=start+count*HOUR-1, limit=count)
    if not isinstance(rows, list) or len(rows) != count:
        raise ValueError('Incomplete candle response')
    for i, row in enumerate(rows):
        if len(row) != 12 or int(row[0]) != start+i*HOUR or int(row[6]) != start+(i+1)*HOUR-1:
            raise ValueError('Candle timestamp or schema mismatch')
    frame = pd.DataFrame([dict(symbol='BTC', open_time=pd.to_datetime(int(r[0]), unit='ms', utc=True),
        open_price=float(r[1]), high_price=float(r[2]), low_price=float(r[3]), close_price=float(r[4]),
        volume_quote=float(r[7]), trade_count=float(r[8])) for r in rows])
    from pipeline.decision.hourly_features import prepare_grid
    if not prepare_grid(frame)[2].all():
        raise ValueError('Invalid OHLCV candle')
    return rows, frame


def versions():
    return {name: importlib.metadata.version(name) for name in PACKAGES}


def initialize(source, root, days=30):
    source, root = Path(source).resolve(), Path(root).resolve()
    if days != 30:
        raise ValueError('Protocol fixes evaluation at 30 days')
    recipe = json.loads((source/'selected_recipe.json').read_text())
    if digest((source/'selected_model.ubj').read_bytes()) != recipe['model_sha256']:
        raise ValueError('Source model hash mismatch')
    now = clock(API)
    start = (now//HOUR+1)*HOUR
    study = root/str(uuid4())
    study.mkdir(parents=True, exist_ok=False)
    project = Path(__file__).resolve().parents[2]
    frozen = study/'frozen'
    shutil.copytree(project/'pipeline', frozen/'pipeline', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (frozen/'scripts').mkdir()
    (frozen/'scripts/__init__.py').touch()
    shutil.copy2(project/'scripts/hourly_future.py', frozen/'scripts/hourly_future.py')
    candidate = study/'candidate'
    candidate.mkdir()
    for name in ('selected_model.ubj', 'selected_recipe.json', 'plan.json'):
        shutil.copy2(source/name, candidate/name)
    assets = {str(p.relative_to(study)): digest(p.read_bytes()) for folder in (frozen, candidate)
              for p in folder.rglob('*') if p.is_file()}
    plan = dict(protocol='btc-hourly-future-v1', created_server_ms=now, source_run=str(source),
        start_ms=start, end_ms=start+30*24*HOUR, expected_hours=720, api=API,
        prediction_delay_limit_seconds=120, scheduler='launchd hourly at minute 1; no historical forecast catchup',
        target='ln(target_close / frozen_previous_close)', target_threshold_relative_mae=.95,
        minimum_coverage=.95, baseline_log_return=0, retrain=False, live_promotion=False,
        model_sha256=recipe['model_sha256'], assets=assets, versions=versions(),
        python_version=sys.version, score_policy='After full window only; paired issued forecasts; missing slots reported',
        label_policy='First valid REST target candle observed at least 60s after close; never revise',
        delay_policy='Inputs end at hour boundary; issued <=120s into target hour; delayed issue disclosed',
        immutability='Local exclusive atomic files, digest verified and read-only; no independent timestamp authority')
    seal(study/'plan.json', plan)
    for relative in assets:
        (study/relative).chmod(0o444)
    for name in ('forecasts', 'labels', 'events'):
        (study/name).mkdir()
    return study


def verify(study):
    study = Path(study)
    plan = unseal(study/'plan.json')
    for relative, expected in plan['assets'].items():
        if digest((study/relative).read_bytes()) != expected:
            raise ValueError(f'Frozen asset changed: {relative}')
    if versions() != plan['versions'] or sys.version != plan['python_version']:
        raise ValueError('Frozen runtime version changed')
    return plan


@contextmanager
def lock(study):
    with (Path(study)/'.worker.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def record_forecast(study, plan, now):
    study = Path(study)
    target = now//HOUR*HOUR
    path = study/'forecasts'/f'{target}.json'
    if not plan['start_ms'] <= target < plan['end_ms']:
        return 'outside_window'
    if path.exists():
        unseal(path)
        return 'already_recorded'
    if now-target > plan['prediction_delay_limit_seconds']*1000:
        return 'deadline_missed'
    rows, frame = klines(plan['api'], target-169*HOUR, 169)
    predicted = predict_candidate(study/'candidate', frame)
    if not math.isfinite(predicted):
        raise ValueError('Non-finite prediction')
    issued = clock(plan['api'])
    if issued < now or issued-target > plan['prediction_delay_limit_seconds']*1000:
        raise ValueError('Prediction finished after deadline or clock moved backwards')
    payload = dict(target_open_ms=target, target_close_ms=target+HOUR, issued_server_ms=issued,
                   issued_local_ms=int(time.time()*1000), input_last_close_ms=target-1,
                   predicted_log_return=predicted, baseline_log_return=0,
                   reference_close=float(frame.close_price.iloc[-1]), input_klines=rows,
                   input_sha256=digest(canonical(rows)), model_sha256=plan['model_sha256'],
                   plan_sha256=digest((study/'plan.json').read_bytes()))
    # Recheck elapsed local time immediately before publishing, after serialization work.
    if time.time()*1000-target > plan['prediction_delay_limit_seconds']*1000:
        raise ValueError('Publication deadline missed')
    seal(path, payload)
    return 'recorded'


def collect_labels(study, plan, now):
    study = Path(study)
    count = 0
    for path in sorted((study/'forecasts').glob('*.json')):
        forecast = unseal(path)
        label_path = study/'labels'/path.name
        if label_path.exists():
            unseal(label_path)
            continue
        if now < forecast['target_close_ms']+60_000:
            continue
        rows, frame = klines(plan['api'], forecast['target_open_ms'], 1)
        seal(label_path, dict(target_open_ms=forecast['target_open_ms'], observed_server_ms=clock(plan['api']),
             close=float(frame.close_price.iloc[0]), raw_kline=rows[0],
             forecast_sha256=digest(path.read_bytes())))
        count += 1
        if count == 24:
            break
    return count


def status(study):
    plan = verify(study)
    return dict(start_utc=pd.to_datetime(plan['start_ms'], unit='ms', utc=True).isoformat(),
        end_utc=pd.to_datetime(plan['end_ms'], unit='ms', utc=True).isoformat(),
        forecasts=len(list((Path(study)/'forecasts').glob('*.json'))),
        labels=len(list((Path(study)/'labels').glob('*.json'))), expected=plan['expected_hours'])


def tick(study):
    study = Path(study)
    with lock(study):
        plan = verify(study)
        if (study/'final_score.json').exists():
            return dict(status='complete', score=unseal(study/'final_score.json'))
        now = clock(plan['api'])
        event = dict(server_ms=now)
        try:
            event['forecast'] = record_forecast(study, plan, now)
            event['labels_added'] = collect_labels(study, plan, now)
        except Exception as error:
            event['error'] = f'{type(error).__name__}: {error}'
            raise
        finally:
            seal(study/'events'/f'{int(time.time()*1000)}-{uuid4()}.json', event)
    if now >= plan['end_ms']+60_000:
        return dict(event=event, score=score(study))
    return event


def score(study):
    study = Path(study)
    with lock(study):
        plan = verify(study)
        now = clock(plan['api'])
        if now < plan['end_ms']+60_000:
            raise ValueError('No interim scoring: evaluation window has not closed')
        if (study/'final_score.json').exists():
            return unseal(study/'final_score.json')
        collect_labels(study, plan, now)
        errors, baselines, missing_forecasts, missing_labels = [], [], [], []
        for target in range(plan['start_ms'], plan['end_ms'], HOUR):
            path = study/'forecasts'/f'{target}.json'
            if not path.exists():
                missing_forecasts.append(target)
                continue
            f = unseal(path)
            if (f['target_open_ms'] != target or not target <= f['issued_server_ms'] <= target+120_000
                    or f['input_last_close_ms'] != target-1 or f['model_sha256'] != plan['model_sha256']
                    or f['input_sha256'] != digest(canonical(f['input_klines']))
                    or f['plan_sha256'] != digest((study/'plan.json').read_bytes())):
                raise ValueError('Invalid forecast audit record')
            label_path = study/'labels'/path.name
            if not label_path.exists():
                missing_labels.append(target)
                continue
            label = unseal(label_path)
            if (label['forecast_sha256'] != digest(path.read_bytes()) or label['target_open_ms'] != target
                    or label['observed_server_ms'] < target+HOUR+60_000):
                raise ValueError('Invalid label audit record')
            actual = math.log(label['close']/f['reference_close'])
            errors.append(abs(actual-f['predicted_log_return']))
            baselines.append(abs(actual))
        if missing_labels:
            raise ValueError(f'{len(missing_labels)} issued forecasts lack labels; collect before final scoring')
        coverage = len(errors)/plan['expected_hours']
        ratio = sum(errors)/sum(baselines) if sum(baselines) else None
        result = dict(scored_server_ms=now, n=len(errors), expected=plan['expected_hours'], coverage=coverage,
            mae=float(np.mean(errors)) if errors else None, zero_mae=float(np.mean(baselines)) if baselines else None,
            relative_mae=ratio, missing_forecasts=missing_forecasts, live_promotion=False,
            decision='inconclusive_coverage' if coverage < plan['minimum_coverage'] or ratio is None else
                     ('target_met' if ratio <= plan['target_threshold_relative_mae'] else 'target_not_met'))
        seal(study/'final_score.json', result)
        return result
