"""Verify an EDA snapshot, cached source archives and hand-calculated examples.

Read-only: no DB changes, no training and no lineage inferred for legacy facts.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
from html import escape
import json
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.batch.binance_archive_downloader import fetch
from pipeline.batch.binance_archive_format import kline_url, parse_kline_csv, read_zip_csv
from pipeline.settings import BINANCE_DATA_URL
from scripts.eda_analysis import coverage, lag_probe, price_panels, safe_correlation, validate_frame
from scripts.run_eda import json_safe, utc_arg


def inspect_archives(frame, raw_dir, interval='1d'):
    """Check every linked local ZIP against the recorded snapshot checksum."""
    linked = frame.loc[frame.sha256.notna() & frame.source_file.notna()]
    if linked.groupby(['symbol', 'source_file']).sha256.nunique().gt(1).any():
        raise ValueError('Conflicting archive versions in snapshot; cache path alone cannot resolve them')
    archives = []
    for (symbol, name, expected), rows in linked.groupby(['symbol', 'source_file', 'sha256']):
        if Path(name).name != name:
            raise ValueError('Archive filename must not contain directories')
        path = raw_dir / 'binance' / f'{symbol}USDT' / interval / name
        if not path.is_file():
            raise FileNotFoundError(f'Cannot verify missing archive: {path}')
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f'Local ZIP differs from recorded SHA-256: {name}')
        # Compare each linked fact against the exact candle in its archive.
        candles = {pd.Timestamp(row['open_time']): row for row in parse_kline_csv(read_zip_csv(path))}
        for _, fact in rows.iterrows():
            candle = candles.get(fact.open_time)
            if candle is None:
                raise ValueError(f'{name} does not contain candle {fact.open_time}')
            columns = ['open_price', 'high_price', 'low_price', 'close_price', 'volume_quote']
            if 'trade_count' in rows.columns:
                columns.append('trade_count')
            for column in columns:
                # Warehouse schema rounds OHLC to 10 and quote volume to 2 decimal places.
                tolerance = Decimal('.00500001') if column == 'volume_quote' else Decimal('.000000000051')
                difference = abs(Decimal(str(fact[column])) - Decimal(candle[column]))
                # Snapshot stores float8; account for its numerical representation too.
                tolerance += abs(Decimal(candle[column])) * Decimal('0.000000000000001')
                if difference > tolerance:
                    raise ValueError(f'{name}: {column} differs from archive at {fact.open_time}')
        archives.append({'symbol':symbol,'source_file':name,'sha256':actual,'linked_facts':len(rows)})
    return archives


def manual_examples(frame, start, end):
    symbols = sorted(frame.symbol.unique())
    cov, index = coverage(frame, symbols, start, end, pd.Timedelta(days=1))
    close, simple, log = price_panels(frame, symbols, index)
    if 'BTC' not in close or len(close.BTC.dropna()) < 2:
        raise ValueError('Need at least two BTC candles for the worked examples')
    valid = simple.BTC.dropna()
    # A concrete consecutive pair, not a handpicked prediction success.
    stamp = valid.index[0]
    previous_stamp = stamp - pd.Timedelta(days=1)
    previous, current = float(close.loc[previous_stamp,'BTC']), float(close.loc[stamp,'BTC'])
    returns = {'previous_open_time':previous_stamp,'target_open_time':stamp,
               'previous_close':previous,'current_close':current,
               'simple_return':current / previous - 1,
               'log_return':float(np.log(current / previous))}
    prices = close.BTC.dropna()
    drawdowns = prices / prices.cummax() - 1
    trough_stamp = drawdowns.idxmin()
    peak_stamp = prices.loc[:trough_stamp].idxmax()
    peak, trough = float(prices.loc[peak_stamp]), float(prices.loc[trough_stamp])
    drawdown = {'peak_open_time':peak_stamp,'peak_close':peak,
                'trough_open_time':trough_stamp,'trough_close':trough,'drawdown':trough / peak - 1}
    correlations = {}
    if 'ETH' in close:
        contemporaneous = pd.concat([log.BTC,log.ETH],axis=1).dropna()
        lagged = pd.DataFrame({'btc_previous':log.BTC.shift(1),'eth_target':log.ETH}).dropna()
        correlations = {'same_period':safe_correlation(contemporaneous.BTC,contemporaneous.ETH),
                        'same_period_n':len(contemporaneous),
                        'btc_previous_to_eth_target':safe_correlation(lagged.btc_previous,lagged.eth_target),
                        'lagged_n':len(lagged)}
    split_at = index[int(len(index) * .75)]
    probe = lag_probe(simple.BTC,split_at)
    sensitivity = {str(block):lag_probe(simple.BTC,split_at,block).get('difference_ci_pp') for block in [3,7,14]}
    return cov, {'return':returns,'drawdown':drawdown,'correlations':correlations,
                 'btc_lag_probe':probe,'bootstrap_block_sensitivity':sensitivity}


def render_checks(report, output):
    example = report['examples']
    ret, dd = example['return'], example['drawdown']
    corr, probe = example['correlations'], example['btc_lag_probe']
    def n(value, digits=6):
        return f'{value:,.{digits}f}'
    def section(title, text):
        return f'<section><h2>{title}</h2>{text}</section>'
    sections = []
    sections.append(section('1. Kiểm đủ nến và nguồn — hai câu hỏi khác nhau',
        f'<p>Snapshot có <b>{report["rows"]:,} dòng</b>; thiếu <b>{sum(row["requested_missing"] for row in report["coverage"])} nến</b> trong khoảng yêu cầu.</p>' +
        f'<p>Đã tính lại SHA-256 của <b>{report["local_archives_checked"]} ZIP</b> trong cache và so với checksum được ghi cùng fact. '
        f'Đã đối chiếu OHLC/quote volume của <b>{report["linked_facts_checked"]:,} fact có lineage</b> với đúng dòng CSV trong ZIP.</p>' +
        f'<p><b>{report["legacy_facts_without_lineage"]} fact không có đủ liên kết nguồn</b>: không được tính vào số fact đã đối chiếu, không tự gán ZIP bằng suy đoán.</p>' +
        f'<p>Checksum phía nhà cung cấp: kiểm <b>{len(report["provider_checksum_samples"])}</b> archive mẫu (mỗi coin một file). '
        'Khớp checksum chứng minh nội dung file khớp bản công bố tại lúc kiểm, không chứng minh giá Binance luôn chính xác.</p>'))
    sections.append(section('2. Tự tính một return BTC từ giá thật',
        f'<p>Nến {escape(str(ret["previous_open_time"])[:10])}: close = <b>{n(ret["previous_close"],2)} USDT</b>.<br>'
        f'Nến {escape(str(ret["target_open_time"])[:10])}: close = <b>{n(ret["current_close"],2)} USDT</b>.</p>'
        f'<pre>simple return = {ret["current_close"]} / {ret["previous_close"]} − 1\n'
        f'              = {n(ret["simple_return"],8)} = {n(ret["simple_return"] * 100,4)}%\n'
        f'log-return    = ln({ret["current_close"]} / {ret["previous_close"]})\n'
        f'              = {n(ret["log_return"],8)}</pre>'
        '<p>Đây là return giữa hai giá đóng, không phải giữa open và close của cùng ngày. Cần cả hai nến đã đóng mới biết giá trị thực tế này.</p>'))
    sections.append(section('3. Tự tính drawdown từ một đỉnh đến đáy sau đó',
        f'<p>Đỉnh đã quan sát: <b>{n(dd["peak_close"],2)} USDT</b>, ngày {escape(str(dd["peak_open_time"])[:10])}.<br>'
        f'Đáy sau đỉnh: <b>{n(dd["trough_close"],2)} USDT</b>, ngày {escape(str(dd["trough_open_time"])[:10])}.</p>'
        f'<pre>drawdown = {dd["trough_close"]} / {dd["peak_close"]} − 1\n'
        f'         = {n(dd["drawdown"] * 100,4)}%</pre>'
        '<p>Đỉnh không được lấy từ tương lai sau đáy. Đây là mức sụt của <b>giá đóng quan sát</b>, không phải drawdown intraday hoặc drawdown chiến lược giao dịch.</p>'))
    if corr:
        sections.append(section('4. Cùng kỳ khác trễ một kỳ như thế nào?',
            f'<p>BTC[t] và ETH[t]: correlation log-return <b>{n(corr["same_period"],4)}</b>, {corr["same_period_n"]} mẫu.<br>'
            f'BTC[t−1] và ETH[t]: <b>{n(corr["btc_previous_to_eth_target"],4)}</b>, {corr["lagged_n"]} mẫu. Cả hai số ở đây dùng toàn khoảng EDA.</p>'
            '<p>Muốn đoán ETH[t] sau khi nến t−1 đóng thì chỉ biết BTC[t−1]. BTC[t] chỉ biết khi kỳ t đã kết thúc — dùng nó như đầu vào dự báo ETH[t] là nhìn tương lai.</p>'
            '<p><b>Trễ là điều kiện về thời gian, không phải bảo đảm có tín hiệu.</b> Để kết luận model hữu ích vẫn phải kiểm ngoài mẫu. Khác với trang EDA, số trễ ở đây là toàn khoảng, không phải chỉ holdout.</p>'))
    if probe['available']:
        ci = probe['difference_ci_pp']
        sections.append(section('5. Baseline và CI: mình có thực sự tốt hơn không?',
            f'<p>BTC, {probe["test_n"]} mẫu holdout, mốc chia {escape(probe["split_at"])}.<br>'
            f'Momentum một kỳ: <b>{n(probe["rule_accuracy_pct"],2)}%</b>; baseline hướng phổ biến train: '
            f'<b>{n(probe["baseline_accuracy_pct"],2)}%</b>.<br>'
            f'Chênh: <b>{n(probe["accuracy_difference_pp"],2)} điểm %</b>; bootstrap CI 95%: '
            f'<b>[{n(ci[0],2)}, {n(ci[1],2)}] điểm %</b>.</p>'
            '<p>Khoảng này chứa 0 → chưa có bằng chứng quy tắc vượt baseline. Không diễn giải là “95% xác suất model tốt hơn”. Đây là khoảng ước lượng theo quy trình lấy mẫu lại, còn phụ thuộc giả định và độ dài block.</p>'
            '<p>Độ nhạy khi đổi block (nến):</p><pre>' + escape(json.dumps(example['bootstrap_block_sensitivity'],indent=2)) + '</pre>'
            '<p>Đã nhìn các kết quả này thì đoạn holdout này là dữ liệu đã dùng khám phá, không tiếp tục gọi nó là test cuối chưa xem.</p>'))
    sections.append(section('6. Chốt bài toán trước khi thêm model',
        '<p><b>EDA ở đây là nến ngày; sản phẩm đã có giao ước khác:</b> dùng nến BTC giờ đã đóng để dự báo <b>log-return một giờ kế tiếp</b>. '
        'Không tự biến thành classifier ngày hoặc xác suất tăng.</p>'
        '<pre>Đầu vào: 169 nến giờ BTC liên tiếp, đã đóng\n'
        '         → 168 hàng đặc trưng theo giao ước\n'
        'Đầu ra: predicted_log_return\n'
        'Giá suy ra: close[t] × exp(predicted_log_return)\n'
        'Nhãn khi huấn luyện: ln(close[t+1] / close[t])</pre>'
        '<p>Chưa train model mới trong bước kiểm chứng này. Đọc tài liệu <code>docs/model_question.md</code> để xem thời điểm ra quyết định, input/output, baseline và kế hoạch test chưa xem.</p>'))
    html = '''<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CoinSight — Tự kiểm chứng dữ liệu và bài toán</title><style>
body{font:16px/1.8 system-ui;color:#193c30;background:#f3f6f3;margin:0}main{max-width:1000px;margin:auto;padding:24px}header,section{background:#fff;border:1px solid #dce6de;border-radius:12px;padding:26px;margin-bottom:20px}h1{line-height:1.3}pre{overflow:auto;background:#edf4ee;padding:16px}code{overflow-wrap:anywhere}footer{font-size:13px;overflow-wrap:anywhere}a{color:#006c54}@media(max-width:600px){main{padding:10px}section,header{padding:16px}}
</style></head><body><main><header><h1>Đã kiểm thật, không chỉ là checklist</h1><p>Ví dụ từ snapshot EDA local. Không sửa dữ liệu, không train model, không giả vờ đã truy nguồn đầy đủ.</p><a href="eda.html">← Báo cáo EDA</a></header>'''
    html += ''.join(sections)
    html += '<footer>Snapshot SHA-256: ' + escape(report['snapshot_sha256']) + '<br>Kiểm lúc ' + escape(report['verified_at']) + '</footer></main></body></html>'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html,encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--summary',type=Path,required=True,help='JSON created by scripts.run_eda')
    parser.add_argument('--raw-dir',type=Path,default=Path('data/raw'))
    parser.add_argument('--verify-provider',action='store_true',help='Fetch published checksums for one linked ZIP per coin')
    parser.add_argument('--output',type=Path,default=Path('frontend/public/reports/eda-checks.html'))
    args = parser.parse_args()
    summary = json.loads(args.summary.read_text())
    meta = summary['metadata']
    if meta['interval'] != '1d':
        parser.error('Worked examples currently require the daily EDA snapshot')
    snapshot = Path(meta['snapshot'])
    actual_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    if actual_hash != meta['snapshot_sha256']:
        raise ValueError('Snapshot CSV SHA-256 does not match the report')
    frame = validate_frame(pd.read_csv(snapshot,float_precision='round_trip'))
    archives = inspect_archives(frame,args.raw_dir)
    provider_samples = []
    if args.verify_provider:
        for symbol in sorted(frame.symbol.unique()):
            selected = next((row for row in archives if row['symbol'] == symbol),None)
            if selected is None:
                continue
            period = selected['source_file'].removeprefix(f'{symbol}USDT-1d-').removesuffix('.zip')
            url = kline_url(BINANCE_DATA_URL,symbol,'1d',period)
            data = fetch(url + '.CHECKSUM')
            if data is None or data.decode().split()[0].lower() != selected['sha256']:
                raise ValueError(f'Provider checksum mismatch/unavailable: {selected["source_file"]}')
            provider_samples.append({**selected,'checksum_url':url + '.CHECKSUM'})
    cov, examples = manual_examples(frame,utc_arg(meta['start']),utc_arg(meta['end_exclusive']))
    report = {'verified_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'snapshot_sha256':actual_hash,'rows':len(frame),'coverage':cov.to_dict('records'),
              'local_archives_checked':len(archives),
              'linked_facts_checked':sum(row['linked_facts'] for row in archives),
              'legacy_facts_without_lineage':len(frame)-sum(row['linked_facts'] for row in archives),
              'provider_checksum_samples':provider_samples,'examples':examples}
    report = json_safe(report)
    evidence_path = args.summary.with_name(args.summary.stem + '-checks.json')
    evidence_path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    render_checks(report,args.output)
    print(json.dumps({'html':str(args.output),'evidence':str(evidence_path),**report},ensure_ascii=False,indent=2,allow_nan=False))


if __name__ == '__main__':
    main()
