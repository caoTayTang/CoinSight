"""Read a consistent warehouse snapshot and generate an explanatory Vietnamese EDA.

Example: python -m scripts.run_eda --start 2024-01-01 --symbols BTC,ETH,SOL,ADA,DOGE,SHIB
This command never downloads, stages or trains anything. Backfill is an explicit step.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from html import escape
import json
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.settings import DATABASE_URL
from scripts.eda_analysis import coverage, lag_probe, price_panels, risk_table, validate_frame


def read_snapshot(url, symbols, start, end, interval):
    import psycopg2
    table = 'dw.fact_ohlcv_daily' if interval == '1d' else 'dw.fact_ohlcv_hourly'
    stamp = "d.full_date::timestamp at time zone 'UTC'" if interval == '1d' else 'f.open_time'
    date_join = 'join dw.dim_date d using (date_key)' if interval == '1d' else ''
    # A single read-only repeatable-read transaction; no mix of different DB states.
    with psycopg2.connect(url) as connection:
        connection.set_session(isolation_level='REPEATABLE READ', readonly=True)
        with connection.cursor() as cursor:
            cursor.execute(f"""select a.symbol, {stamp} as open_time,
                f.open_price::float8, f.high_price::float8, f.low_price::float8,
                f.close_price::float8, f.volume_quote::float8,
                f.batch_id, f.extract_batch_id, f.source_file, m.sha256
                from {table} f join dw.dim_asset a using (asset_key)
                join dw.dim_source s using (source_key) {date_join}
                left join meta.source_file_manifest m
                  on m.extract_batch_id = f.extract_batch_id and m.source_file = f.source_file
                where s.source_code = 'binance' and a.symbol = any(%s)
                  and {stamp} >= %s and {stamp} < %s
                order by a.symbol, {stamp}""", (symbols, start.to_pydatetime(), end.to_pydatetime()))
            return pd.DataFrame(cursor.fetchall(), columns=[c.name for c in cursor.description])


def utc_arg(value):
    stamp = pd.Timestamp(value)
    return stamp.tz_localize('UTC') if stamp.tzinfo is None else stamp.tz_convert('UTC')


def json_safe(value):
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if value is pd.NaT:
        return None
    return value


def describe(frame, symbols, start, end, interval):
    step = pd.Timedelta(days=1) if interval == '1d' else pd.Timedelta(hours=1)
    frame = validate_frame(frame)
    cov, index = coverage(frame, symbols, start, end, step)
    close, simple, log = price_panels(frame, symbols, index)
    common = close.dropna(how='any')
    if len(common) < 60:
        raise ValueError(f'Only {len(common)} common candles; need at least 60. Backfill or narrow symbols explicitly.')
    # Use one common calendar interval for fair risk comparisons, keeping holes.
    shared_close = close.loc[common.index.min():common.index.max()]
    shared_simple = simple.loc[shared_close.index]
    shared_log = log.loc[shared_close.index]
    risk = risk_table(shared_close, shared_simple, shared_log, 365 if interval == '1d' else 365 * 24)
    matched_returns = shared_log.dropna(how='any')
    if len(matched_returns) < 60:
        raise ValueError(f'Only {len(matched_returns)} common consecutive returns; need at least 60. Check gaps/interval.')
    split_at = index[int(len(index) * .75)]
    block = 7 if interval == '1d' else 24
    probes = {symbol: lag_probe(simple[symbol], split_at, block) for symbol in symbols}
    btc = 'BTC' if 'BTC' in symbols else symbols[0]
    returns = simple[btc]
    window = 30 if interval == '1d' else 168
    # At target t, only returns through t-1 are available for regime assignment.
    previous_vol = log[btc].rolling(window, min_periods=window).std().shift(1)
    threshold = previous_vol.loc[previous_vol.index < split_at].median()
    regimes = pd.DataFrame({'target': returns, 'past_vol': previous_vol}).dropna()
    regimes = regimes.loc[regimes.index >= split_at].copy()
    regimes['regime'] = np.where(regimes.past_vol > threshold, 'Biến động cao', 'Biến động thấp')
    regime_rows = []
    for label, group in regimes.groupby('regime'):
        regime_rows.append({'regime': label, 'n': len(group),
                            'mean_abs_next_return_pct': group.target.abs().mean() * 100,
                            'next_up_pct': group.target.gt(0).mean() * 100})
    years = []
    for year, group in returns.dropna().groupby(returns.dropna().index.year):
        years.append({'year': int(year), 'n': len(group),
                      'first': group.index.min(), 'last': group.index.max(),
                      'up_pct': group.gt(0).mean() * 100,
                      'mean_abs_return_pct': group.abs().mean() * 100,
                      'vol_pct_per_period': group.std() * 100,
                      'lag_correlation': group.corr(returns.shift(1).reindex(group.index))})
    return {
        'coverage': cov, 'close': close, 'simple': simple, 'log': log,
        'common': common, 'risk': risk, 'matched_returns': matched_returns,
        'probes': probes, 'split_at': split_at, 'anchor': btc,
        'regimes': pd.DataFrame(regime_rows), 'regime_window': window,
        'regime_threshold': threshold, 'years': pd.DataFrame(years),
    }


def render(frame, results, meta, output):
    import plotly.graph_objects as go
    import plotly.io as pio
    from plotly.offline import get_plotlyjs

    cov = results['coverage']
    close, simple, log = results['close'], results['simple'], results['log']
    symbols = list(close.columns)
    anchor = results['anchor']
    common = results['common']
    matched = results['matched_returns']
    risk = results['risk']
    probes = results['probes']
    is_daily = meta['interval'] == '1d'
    unit = 'ngày' if is_daily else 'giờ'
    annual = 365 if is_daily else 365 * 24
    window = results['regime_window']

    def number(value, suffix='', digits=2):
        return 'chưa đủ dữ liệu' if value is None or not np.isfinite(float(value)) else f'{float(value):,.{digits}f}{suffix}'

    def table(data, rename=None):
        if data.empty:
            return '<p>Chưa đủ dữ liệu.</p>'
        return '<div class="table-scroll">' + data.rename(columns=rename or {}).to_html(
            index=False, border=0, escape=True, na_rep='—', float_format=lambda v: f'{v:,.3f}') + '</div>'

    def chart(fig, title, height=480):
        fig.update_layout(template='plotly_white', title=title, height=height,
                          font={'family': 'system-ui'}, margin={'l': 65, 'r': 30, 't': 65, 'b': 55},
                          hovermode='x unified')
        # Scatter rather than WebGL for offline/mobile compatibility.
        return pio.to_html(fig, full_html=False, include_plotlyjs=False,
                           config={'responsive': True, 'displaylogo': False})

    def section(key, title, content):
        return f'<section id="{key}"><h2>{title}</h2>{content}</section>'

    def finding(title, evidence, meaning, action):
        return f'<article class="finding"><h3>{escape(title)}</h3><p><b>Bằng chứng:</b> {evidence}</p><p><b>Ý nghĩa:</b> {meaning}</p><p><b>Tiếp theo:</b> {action}</p></article>'

    findings = []
    total_missing = int(cov.requested_missing.sum())
    findings.append(finding(
        'Dữ liệu đủ đến đâu?',
        f'{len(frame):,} nến, {len(symbols)} coin; thiếu {total_missing:,} nến trong phạm vi yêu cầu. '
        f'Có {len(matched):,} return đồng thời để so sánh các coin.',
        'Báo cáo đọc trực tiếp snapshot PostgreSQL, không lấy output notebook. Thiếu ngoài hai đầu cũng được tính theo khoảng bạn yêu cầu.',
        'Nếu còn thiếu, kiểm coverage trước khi diễn giải biến động hoặc train model.'))
    arisk = risk.loc[risk.symbol.eq(anchor)].iloc[0]
    findings.append(finding(
        f'{anchor}: độ khó không giống nhau ở mọi giai đoạn',
        f'Trong khoảng chung, drawdown lớn nhất {number(arisk.max_drawdown_pct, "%")}; '
        f'volatility năm hóa {number(arisk.annual_vol_pct, "%")}.',
        'Dự báo gần giá hiện tại có thể có sai số giá nhỏ dù không dự báo được hướng. Return và drawdown giúp nhìn rõ rủi ro bị che bởi đường giá.',
        'So model theo từng năm/giai đoạn và với baseline return = 0, không chỉ báo một MAE giá tổng hợp.'))
    anchor_probe = probes[anchor]
    if anchor_probe['available']:
        ci = anchor_probe['difference_ci_pp']
        evidence = (f'Phần giữ riêng: {anchor_probe["test_n"]} mẫu; theo hướng kỳ trước đúng '
                    f'{number(anchor_probe["rule_accuracy_pct"], "%")}, baseline hướng cố định '
                    f'{number(anchor_probe["baseline_accuracy_pct"], "%")}. Chênh lệch '
                    f'{number(anchor_probe["accuracy_difference_pp"], " điểm %")}.')
        if ci:
            evidence += f' Khoảng bootstrap 95%: [{number(ci[0])}; {number(ci[1])}] điểm %.'
        supported = ci is not None and ci[0] > 0
        findings.append(finding(
            'Hướng kỳ trước có giúp đoán kỳ sau?', evidence,
            'Có tín hiệu sơ bộ vượt baseline trên đoạn này, chưa chứng minh ổn định hoặc sinh lời.' if supported else
            'Chưa có bằng chứng đáng tin rằng quy tắc momentum một kỳ vượt baseline. Đừng mặc định thêm lịch sử sẽ giải quyết được vấn đề.',
            'Giữ quy tắc/split cố định; lần thử feature tiếp theo cần validation theo thời gian và một test mới chưa dùng để chọn feature.'))
    corr = matched.corr(min_periods=60)
    if len(symbols) > 1:
        others = corr[anchor].drop(anchor).dropna()
        if not others.empty:
            other = others.idxmax()
            lagged = pd.DataFrame({'past': log[anchor].shift(1), 'target': log[other]}).loc[results['split_at']:].dropna()
            lag_value = lagged.past.corr(lagged.target) if len(lagged) >= 30 else np.nan
            findings.append(finding(
                'Đi cùng nhau không có nghĩa dự báo được nhau',
                f'{anchor}–{other}: correlation cùng kỳ {number(others[other], digits=3)} trên {len(matched)} mẫu chung; '
                f'{anchor} kỳ trước → {other} kỳ sau trên đoạn giữ riêng: {number(lag_value, digits=3)} ({len(lagged)} mẫu).',
                'Hệ số cùng kỳ phản ánh rủi ro chung, không phải xác suất dự đoán. Cặp được chọn vì có correlation cùng kỳ cao nhất nên kiểm tra trễ này chỉ là khám phá.',
                'Không gọi correlation cùng kỳ là feature dự báo; kiểm riêng độ trễ và không chọn cặp bằng kết quả test.'))

    parts = [f'''<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CoinSight — EDA từ warehouse</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f3f6f3;color:#17392f;font:16px/1.75 system-ui,sans-serif}}main{{max-width:1240px;margin:auto;padding:28px 24px 80px}}header,section{{background:white;border:1px solid #dce6de;border-radius:14px;padding:28px;margin-bottom:24px}}h1{{font-size:clamp(30px,4vw,46px);line-height:1.2}}h2{{font-size:26px}}h3{{font-size:18px}}a{{color:#006b54}}nav{{display:flex;gap:16px;flex-wrap:wrap}}.notice{{padding:16px;background:#fff4d9;border-left:4px solid #bd8727}}.explain{{padding:16px;background:#edf6f0;border-radius:8px}}.findings{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}.finding{{border:1px solid #dce6de;border-top:4px solid #08735b;border-radius:9px;padding:18px}}.finding h3{{margin-top:0}}.finding p{{font-size:14px}}.table-scroll{{overflow:auto}}table{{border-collapse:collapse;white-space:nowrap;width:100%;font-size:13px}}td,th{{text-align:right;border-bottom:1px solid #dce6de;padding:10px}}td:first-child,th:first-child{{text-align:left}}code{{background:#eef3ee;padding:2px 6px;border-radius:4px;overflow-wrap:anywhere}}pre{{overflow:auto;background:#edf3ee;padding:16px;font-size:13px}}.meta{{font-size:13px;color:#50695d;overflow-wrap:anywhere}}li{{margin:7px 0}}@media(max-width:760px){{main{{padding:12px}}section,header{{padding:17px}}.findings{{grid-template-columns:1fr}}}}
</style><script>{get_plotlyjs()}</script></head><body><main><header><p>COINSIGHT · EDA CHẠY LẠI TỪ POSTGRESQL</p><h1>Không chỉ vẽ biểu đồ: dữ liệu giúp quyết định gì?</h1>
<p>{escape(', '.join(symbols))} · nến {meta['interval']} · nguồn Binance Spot · {len(frame):,} dòng.</p>
<p>Yêu cầu: <b>{escape(meta['start'])}</b> đến trước <b>{escape(meta['end_exclusive'])}</b> (UTC). Snapshot đọc lúc {escape(meta['generated_at'])}.</p>
<div class="notice">Đây là EDA mô tả dữ liệu và thử một quy tắc dự báo cố định, không phải model đã được chứng nhận. Phạm vi nến {unit} không cho phép kết luận về dự báo nến giờ nếu đang phân tích nến ngày.</div>
<nav><a href="#findings">Kết luận</a><a href="#quality">Dữ liệu</a><a href="#risk">Giai đoạn/rủi ro</a><a href="#co-movement">Tương quan</a><a href="#signal">Tín hiệu trễ</a><a href="#volatility">Chế độ biến động</a><a href="#candles">Nến thật</a><a href="#reproduce">Chạy lại</a><a href="eda-checks.html">Ví dụ kiểm chứng thật</a></nav></header>''']
    regime_summary = results['regimes']
    if set(regime_summary.get('regime', [])) == {'Biến động cao', 'Biến động thấp'}:
        high = regime_summary.loc[regime_summary.regime.eq('Biến động cao')].iloc[0]
        low = regime_summary.loc[regime_summary.regime.eq('Biến động thấp')].iloc[0]
        findings.append(finding(
            'Độ lớn biến động có thể hữu ích hơn hướng',
            f'{anchor} holdout: sau trạng thái biến động cao, |return kế tiếp| trung bình '
            f'{number(high.mean_abs_next_return_pct, "%")} ({int(high.n)} mẫu), so với '
            f'{number(low.mean_abs_next_return_pct, "%")} ({int(low.n)} mẫu) ở trạng thái thấp.',
            'Đây là dấu hiệu mô tả về mức rủi ro kế tiếp, không phải bằng chứng dự báo hướng hoặc quan hệ nhân quả.',
            'Ưu tiên kiểm feature volatility cho cảnh báo rủi ro; cần kiểm thêm độ ổn định và khoảng bất định.'))
    parts.append(section('findings', f'1. Kết luận chính — {len(findings)} điều cần rút ra', '<div class="findings">' + ''.join(findings) + '</div>'))
    parts.append(section('quality', '2. Trước khi tin kết luận: dữ liệu có đủ không?',
        '<p>Đếm thiếu theo <b>toàn bộ khoảng yêu cầu</b>, không chỉ giữa nến đầu/cuối. Không forward-fill giá, không biến return nhiều ngày thành return một ngày. Nến sai OHLC/volume hoặc khóa trùng khiến script dừng, không âm thầm bỏ qua.</p>' +
        table(cov, {'symbol':'Coin','rows':'Nến','first':'Đầu','last':'Cuối','internal_missing':'Thiếu giữa',
                    'requested_missing':'Thiếu trong yêu cầu','requested_expected':'Kỳ vọng','lineage_missing':'Chưa có SHA-256 nguồn'}) +
        '<p><b>Thiếu đầu/cuối</b> có thể do phạm vi chưa nạp hoặc chưa niêm yết, cần xác minh trước khi gọi là lỗi. <b>Chưa có SHA-256</b> có thể là fact cũ trước migration; không tự suy ra nguồn. Hash snapshot xác định dữ liệu dùng phân tích, không thay thế checksum archive.</p>'))

    rebased = common.div(common.iloc[0]).mul(100)
    trend = go.Figure([go.Scatter(x=rebased.index, y=rebased[s], name=s, mode='lines', connectgaps=False) for s in symbols])
    trend.update_yaxes(type='log', title='Chỉ số giá, cùng mốc đầu = 100 · trục log')
    dd = close.loc[common.index.min():common.index.max()]
    drawdown = dd / dd.cummax() - 1
    draw = go.Figure([go.Scatter(x=drawdown.index, y=drawdown[s] * 100, name=s, mode='lines', connectgaps=False) for s in symbols])
    draw.update_yaxes(title='Giảm từ đỉnh đã quan sát (%)')
    year_names = {'year':'Năm','n':'Return hợp lệ','first':'Từ','last':'Đến','up_pct':'Tỷ lệ tăng (%)',
                  'mean_abs_return_pct':f'Biến động tuyệt đối TB/{unit} (%)','vol_pct_per_period':f'Std return/{unit} (%)','lag_correlation':'Corr với kỳ trước'}
    worst_days = simple[anchor].nsmallest(5).index
    stress = simple.loc[worst_days].mul(100).reset_index().rename(columns={'index':'Thời điểm mở nến'})
    parts.append(section('risk', '3. Rủi ro và cấu trúc thị trường có ổn định không?',
        f'<p>So sánh trên cùng khoảng {common.index.min().date()} → {common.index.max().date()}; không so coin A từ 2020 với coin B từ 2021. Return chỉ dùng cặp nến liên tiếp. Nếu coverage còn thiếu, mức drawdown quan sát có thể bỏ sót chuyển động trong khoảng trống.</p>' +
        chart(trend, 'Cùng ngày bắt đầu, cùng mốc 100 — coin nào tăng/giảm tương đối?') +
        table(risk, {'symbol':'Coin','n_returns':'Số return','total_return_pct':'Tổng thay đổi (%)','up_pct':'Tỷ lệ tăng (%)','flat_pct':'Tỷ lệ đứng giá (%)',
                     'annual_vol_pct':'Vol năm hóa (%)','max_drawdown_pct':'Drawdown lớn nhất (%)','worst_return_pct':'Kỳ xấu nhất (%)','best_return_pct':'Kỳ tốt nhất (%)'}) +
        chart(draw, 'Tăng trưởng có đi kèm sụt giảm sâu?') +
        f'<h3>{anchor} theo từng năm — năm đầu/cuối có thể chưa đủ năm</h3>' + table(results['years'], year_names) +
        '<div class="explain"><b>Quyết định:</b> train/test phải theo thời gian, báo kết quả từng giai đoạn. Nhiều nến hơn không đảm bảo phân phối tương lai giống quá khứ. Độ biến động năm hóa là phép quy đổi mô tả, không phải dự báo chắc chắn.</div>' +
        f'<h3>5 kỳ giảm mạnh nhất của {anchor}: các coin khác phản ứng thế nào?</h3>' + table(stress) +
        '<p>Đơn vị bảng là simple return %. Không gán tên sự kiện khi chưa đối chiếu nguồn tin. Dùng những kỳ này để xem rủi ro chung, không tự động xóa như outlier.</p>'))

    corr_chart = go.Figure(go.Heatmap(x=corr.columns, y=corr.index, z=corr.to_numpy(), zmin=-1,zmax=1,
                                    colorscale='RdBu_r', text=corr.round(2).to_numpy(), texttemplate='%{text}',
                                    hovertemplate='%{y} / %{x}: %{z:.3f}<extra></extra>'))
    corr_chart.update_layout(hovermode='closest')
    rolling = go.Figure()
    for symbol in symbols:
        if symbol != anchor:
            series = log[anchor].rolling(90 if is_daily else 168, min_periods=60).corr(log[symbol])
            rolling.add_trace(go.Scatter(x=series.index,y=series,name=f'{anchor}–{symbol}',connectgaps=False))
    rolling.update_yaxes(title='Pearson correlation', range=[-1,1])
    parts.append(section('co-movement','4. Nhiều coin có thật sự giúp đa dạng hóa?',
        f'<p>Heatmap dùng <b>cùng {len(matched)} timestamp return</b> cho mọi cặp — không so hệ số trên các thời kỳ khác nhau. Đây là log-return cùng kỳ, không phải mức giá.</p>' +
        chart(corr_chart,'Coin nào cùng biến động trên cùng tập thời điểm?') +
        chart(rolling,f'Correlation trượt với {anchor} — quan hệ có ổn định không?') +
        '<div class="explain"><b>Quyết định:</b> các coin tương quan cao có thể mang cùng rủi ro thị trường. Chia tiền ra nhiều tên coin không tự động đa dạng hóa. Correlation không phải quan hệ nhân quả, không phải xác suất dự báo đúng, và không đo đầy đủ phụ thuộc ở đuôi phân phối.</div>'))

    probe_rows = []
    for symbol, probe in probes.items():
        if probe['available']:
            ci = probe['difference_ci_pp']
            probe_rows.append({'Coin':symbol,'Train':probe['train_n'],'Holdout':probe['test_n'],
                'Corr trễ train':probe['train_lag_correlation'],'Corr trễ holdout':probe['test_lag_correlation'],
                'Momentum đúng (%)':probe['rule_accuracy_pct'],'Baseline đúng (%)':probe['baseline_accuracy_pct'],
                'Chênh (điểm %)':probe['accuracy_difference_pp'],
                'CI 95% (điểm %)':f'[{ci[0]:.2f}, {ci[1]:.2f}]' if ci else 'Chưa đủ mẫu',
                'MAE return=0 (điểm %)':probe['zero_return_mae'] * 100,
                'MAE return=kỳ trước (điểm %)':probe['previous_return_mae'] * 100})
        else:
            probe_rows.append({'Coin':symbol,'Train':probe['train_n'],'Holdout':probe['test_n'], 'CI 95% (điểm %)':'Không đủ mẫu'})
    parts.append(section('signal','5. Câu hỏi dự báo thật: biết kỳ trước có giúp biết kỳ sau?',
        f'<p><b>Target:</b> simple return <code>close[t] / close[t−1] − 1</code>. Tại thời điểm dự báo, chỉ biết return đến kỳ t−1. <b>Quy tắc cố định:</b> kỳ trước tăng thì dự đoán tăng, ngược lại dự đoán không tăng. Return bằng 0 thuộc lớp không tăng.</p>' +
        f'<p><b>Chia theo thời gian:</b> 75% đầu khoảng lịch yêu cầu là train, 25% cuối giữ riêng; mốc {results["split_at"].isoformat()}. Baseline luôn đoán lớp phổ biến trên <b>train</b>, không chọn lớp trên holdout. Không shuffle, không chọn rule theo holdout.</p>' +
        table(pd.DataFrame(probe_rows)) +
        f'<p>CI: moving-block bootstrap {7 if is_daily else 24} nến, 500 lần, seed 42, trên chênh lệch đúng/sai của cùng các mẫu holdout. Nếu khoảng chứa 0 thì chưa có bằng chứng quy tắc vượt baseline; đây là khoảng thăm dò, không điều chỉnh cho việc xem nhiều coin và phụ thuộc vào độ dài block.</p>' +
        '<div class="explain"><b>Đọc metric:</b> accuracy 51% chưa chắc hơn baseline 53%. MAE return=0 là dự báo giá kỳ sau bằng giá hiện tại, thường khó vượt ở kỳ ngắn. Hệ số tương quan trễ gần 0 giải thích vì sao thêm model phức tạp có thể vẫn ít cải thiện.</div>' +
        '<p><b>Giới hạn:</b> chưa train classifier/XGBoost; chưa tính spread, phí, slippage, lợi nhuận. Holdout đã xem trong EDA thì không được tiếp tục dùng như test cuối để chọn feature. Mốc timestamp là lúc mở nến; OHLC/return của nến đó chỉ biết sau khi đóng.</p>'))

    regimes = results['regimes']
    regime_plot = go.Figure()
    if not regimes.empty:
        regime_plot.add_trace(go.Bar(x=regimes.regime,y=regimes.mean_abs_next_return_pct,text=regimes.n,
                                     hovertemplate='%{x}<br>|return| TB: %{y:.3f}%<br>n=%{text}<extra></extra>'))
    parts.append(section('volatility','6. Nếu hướng khó đoán, mức độ biến động có hữu ích hơn?',
        f'<p>Lấy std log-return của {window} nến <b>trước target</b>; ngưỡng cao/thấp là median của feature trên train, không tính trên toàn lịch sử. Chỉ thống kê target trong holdout.</p>' +
        table(regimes, {'regime':'Trạng thái đã biết trước','n':'Số mẫu holdout','mean_abs_next_return_pct':'|Return kế tiếp| TB (%)','next_up_pct':'Kế tiếp tăng (%)'}) +
        chart(regime_plot,'Biến động quá khứ cao có đi kèm biên độ kế tiếp cao?') +
        '<div class="explain"><b>Quyết định:</b> nếu nhóm cao có |return| kế tiếp lớn hơn, feature volatility đáng thử cho cảnh báo rủi ro hoặc dự báo độ lớn biến động. Không suy ra nó đoán đúng hướng tăng/giảm. Đây là so sánh mô tả, chưa kiểm độ tin cậy của chênh lệch.</div>'))

    candle = go.Figure()
    actual = frame.loc[frame.symbol.eq(anchor)].tail(180)
    candle.add_trace(go.Candlestick(x=actual.open_time,open=actual.open_price,high=actual.high_price,
                                    low=actual.low_price,close=actual.close_price,name=anchor))
    ma = close[anchor].rolling(20,min_periods=20).mean().reindex(actual.open_time)
    candle.add_trace(go.Scatter(x=actual.open_time,y=ma,name='MA 20 nến',mode='lines'))
    candle.update_layout(xaxis_rangeslider_visible=False,yaxis_title='USDT',hovermode='closest')
    parts.append(section('candles','7. Kiểm bằng mắt trên OHLC thật',
        f'<p>{anchor}, tối đa 180 nến cuối từ DB. Đây là OHLC thật, không tái dựng từ chỉ số 100. MA chỉ mô tả quá khứ, không phải dự báo.</p>' +
        chart(candle,f'{anchor}/USDT · {meta["interval"]} · OHLC + MA20',560)))

    parts.append(section('reproduce','8. Tự kiểm chứng và chạy lại',
        '<p><a href="eda-checks.html">Mở bản kiểm chứng đã chạy: archive/checksum, return, drawdown, correlation và baseline/CI →</a></p>' +
        '<ol><li>Kiểm riêng độ phủ nến và khả năng truy tới archive/checksum; đủ nến không đồng nghĩa đã truy nguồn đầy đủ.</li><li>Tính lại return từ hai giá đóng và drawdown từ đỉnh trước đáy — có ví dụ số thật trong bản kiểm chứng.</li><li>So cùng kỳ với trễ một kỳ: đầu vào phải tồn tại trước khi mục tiêu được biết.</li><li>So với baseline trên cùng mẫu và đọc CI của chênh lệch, không chỉ nhìn accuracy.</li><li>Khóa feature/config bằng train/validation; phần 2026 đã xem là khám phá, cần chốt test tương lai mới trước khi đánh giá cuối.</li></ol>' +
        '<p>Script này chỉ SELECT từ DB, không backfill và không chạy code trong notebook. Snapshot CSV và summary JSON được lưu local để chạy lại đúng dữ liệu kể cả khi DB đổi.</p>' +
        '<pre>' + escape(meta['rerun_command']) + '</pre>' +
        '<p><b>Giữ nguyên snapshot:</b></p><pre>' + escape(meta['snapshot_command']) + '</pre>' +
        '<p><b>Dữ liệu thô:</b> không fill gap; dừng nếu có duplicate hoặc OHLC/volume không hợp lệ. <b>Backfill:</b> là bước riêng, không được script tự chạy âm thầm.</p>' +
        '<p><b>Phạm vi:</b> chỉ 6 coin được chọn, một sàn Binance Spot và cặp USDT; không đại diện mọi crypto hoặc các coin đã hủy niêm yết. Khoảng 2024 được chọn để khởi động EDA, không được chọn vì model có metric tốt nhất. Cần kiểm thêm giai đoạn trước 2024 trước khi tổng quát hóa.</p>'))
    parts.append('<footer class="meta">' + escape(json.dumps(meta, ensure_ascii=False, indent=2)).replace('\n','<br>') +
                 '<p>SHA-256 xác định nội dung snapshot. Đây là EDA, không phải khuyến nghị đầu tư.</p></footer></main></body></html>')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text('\n'.join(parts),encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start',default='2024-01-01')
    parser.add_argument('--end',help='Exclusive UTC date/time; defaults to current UTC day/hour boundary')
    parser.add_argument('--symbols',default='BTC,ETH,SOL,ADA,DOGE,SHIB')
    parser.add_argument('--interval',choices=['1d','1h'],default='1d')
    parser.add_argument('--snapshot',type=Path,help='Rerun a previously exported CSV instead of reading DB')
    parser.add_argument('--database-url',default=DATABASE_URL)
    parser.add_argument('--output',type=Path,default=Path('frontend/public/reports/eda.html'))
    parser.add_argument('--artifacts',type=Path,default=Path('data/eda'))
    args = parser.parse_args()
    symbols = list(dict.fromkeys(s.strip().upper() for s in args.symbols.split(',') if s.strip()))
    if not symbols:
        parser.error('At least one symbol required')
    frequency = 'D' if args.interval == '1d' else 'h'
    now = pd.Timestamp.now(tz='UTC')
    start = utc_arg(args.start)
    end = utc_arg(args.end) if args.end else now.floor(frequency)
    if start != start.floor(frequency) or end != end.floor(frequency) or start >= end:
        parser.error('Start/end must be aligned UTC boundaries and start < end')
    if end > now.floor(frequency):
        parser.error('End must exclude the currently open candle')
    if args.snapshot:
        frame = pd.read_csv(args.snapshot, float_precision='round_trip')
        frame['open_time'] = pd.to_datetime(frame.open_time,utc=True)
        frame = frame.loc[frame.symbol.isin(symbols) & frame.open_time.ge(start) & frame.open_time.lt(end)].copy()
    else:
        frame = read_snapshot(args.database_url,symbols,start,end,args.interval)
    if frame.empty:
        raise ValueError('No data. Backfill the selected scope first.')
    if (pd.to_datetime(frame.open_time,utc=True) != pd.to_datetime(frame.open_time,utc=True).dt.floor(frequency)).any():
        raise ValueError('Misaligned candles; snapshot interval does not match requested interval')
    results = describe(frame,symbols,start,end,args.interval)
    frame = validate_frame(frame)
    content = frame.to_csv(index=False,float_format='%.17g').encode()
    digest = hashlib.sha256(content).hexdigest()
    args.artifacts.mkdir(parents=True,exist_ok=True)
    snapshot = args.artifacts / f'eda-{args.interval}-{digest[:12]}.csv'
    snapshot.write_bytes(content)
    scope = f'--start {start.isoformat()} --end {end.isoformat()} --symbols {",".join(symbols)} --interval {args.interval}'
    base = 'uv run --python 3.12 --with-requirements scripts/requirements-eda.txt python -m scripts.run_eda '
    meta = {'generated_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'data_source':'CSV snapshot' if args.snapshot else 'PostgreSQL read-only repeatable-read snapshot',
            'start':start.isoformat(),'end_exclusive':end.isoformat(),'interval':args.interval,
            'symbols':symbols,'snapshot':str(snapshot),'snapshot_sha256':digest,
            'rows':len(frame),'seed':42,'bootstrap_repeats':500,
            'rerun_command':base + scope,
            'snapshot_command':base + scope + f' --snapshot {snapshot}'}
    summary = {'metadata':meta,'coverage':results['coverage'].to_dict('records'),
               'risk':results['risk'].to_dict('records'),'lag_probes':results['probes'],
               'regimes':results['regimes'].to_dict('records')}
    summary_path = args.artifacts / f'eda-{args.interval}-{digest[:12]}.json'
    summary_path.write_text(json.dumps(json_safe(summary),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    render(frame,results,meta,args.output)
    print(json.dumps(json_safe({'html':str(args.output),'summary':str(summary_path),**summary}),ensure_ascii=False,indent=2,allow_nan=False))


if __name__ == '__main__':
    main()
