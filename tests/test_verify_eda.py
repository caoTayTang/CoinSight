import hashlib
from pathlib import Path
import zipfile

import pandas as pd
import pytest

from scripts.verify_eda import inspect_archives, manual_examples


def archive_and_fact(tmp_path):
    name = 'BTCUSDT-1d-2024-01-01.zip'
    path = tmp_path / 'binance' / 'BTCUSDT' / '1d' / name
    path.parent.mkdir(parents=True)
    with zipfile.ZipFile(path,'w') as archive:
        archive.writestr('candle.csv',
            '1704067200000,100,110,90,105,1,1704153599999,100.12345678,10,1,50,0\n')
    frame = pd.DataFrame([{
        'symbol':'BTC','open_time':pd.Timestamp('2024-01-01',tz='UTC'),
        'open_price':100,'high_price':110,'low_price':90,'close_price':105,
        'volume_quote':100.12,'source_file':name,
        'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
    }])
    return path,frame


def test_source_check_allows_only_warehouse_rounding(tmp_path):
    _,frame = archive_and_fact(tmp_path)
    verified = inspect_archives(frame,tmp_path)
    assert len(verified) == 1
    assert verified[0]['linked_facts'] == 1
    frame.loc[0,'close_price'] = 106
    with pytest.raises(ValueError,match='close_price differs'):
        inspect_archives(frame,tmp_path)


def test_hourly_archive_check_also_checks_trade_count(tmp_path):
    path, frame = archive_and_fact(tmp_path)
    hourly = path.parent.parent / '1h' / path.name.replace('-1d-', '-1h-')
    hourly.parent.mkdir()
    path.replace(hourly)
    frame.loc[0, 'source_file'] = hourly.name
    frame['trade_count'] = 10
    assert inspect_archives(frame, tmp_path, interval='1h')[0]['linked_facts'] == 1
    frame.loc[0, 'trade_count'] = 11
    with pytest.raises(ValueError, match='trade_count differs'):
        inspect_archives(frame, tmp_path, interval='1h')


def test_modified_archive_fails_hash_check(tmp_path):
    path,frame = archive_and_fact(tmp_path)
    path.write_bytes(path.read_bytes() + b'changed')
    with pytest.raises(ValueError,match='differs from recorded SHA-256'):
        inspect_archives(frame,tmp_path)


def test_legacy_fact_is_not_claimed_as_verified(tmp_path):
    _,frame = archive_and_fact(tmp_path)
    frame.loc[0,'sha256'] = None
    assert inspect_archives(frame,tmp_path) == []


def test_missing_archive_is_explicit(tmp_path):
    path,frame = archive_and_fact(tmp_path)
    path.unlink()
    with pytest.raises(FileNotFoundError,match='Cannot verify'):
        inspect_archives(frame,tmp_path)


def test_worked_return_and_drawdown_use_consecutive_prices_and_prior_peak():
    frame = pd.DataFrame({
        'symbol':['BTC'] * 3,
        'open_time':pd.date_range('2024-01-01',periods=3,tz='UTC'),
        'close_price':[100.,120.,90.],
    })
    _,examples = manual_examples(frame,pd.Timestamp('2024-01-01',tz='UTC'),
                                pd.Timestamp('2024-01-04',tz='UTC'))
    assert examples['return']['simple_return'] == pytest.approx(.2)
    assert examples['drawdown']['drawdown'] == pytest.approx(-.25)
    assert examples['drawdown']['peak_open_time'] < examples['drawdown']['trough_open_time']
