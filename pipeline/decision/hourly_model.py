"""Train one fixed BTC XGBoost candidate; causal chronological retrospective backtest.

No parameter search, test-driven refit, live deployment or trading simulation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from html import escape
import importlib.metadata
import json
from pathlib import Path
import subprocess
import time
from uuid import uuid4

import numpy as np
import pandas as pd

from pipeline.decision.hourly_features import (FEATURE_COLUMNS, FEATURE_VERSION, build_dataset,
                                              chronological_split, prepare_grid)
from pipeline.settings import DATABASE_URL, SETTINGS


def utc(value):
    stamp = pd.Timestamp(value)
    return stamp.tz_localize('UTC') if stamp.tzinfo is None else stamp.tz_convert('UTC')


def safe_json(value):
    if isinstance(value, dict):
        return {str(k):safe_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_json(v) for v in value]
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def write_json(path, value):
    path.write_text(json.dumps(safe_json(value), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_snapshot(database_url, start, end):
    import psycopg2
    with psycopg2.connect(database_url) as connection:
        connection.set_session(isolation_level='REPEATABLE READ', readonly=True)
        with connection.cursor() as cursor:
            cursor.execute('''select a.symbol, f.open_time,
                f.open_price::float8, f.high_price::float8, f.low_price::float8,
                f.close_price::float8, f.volume_quote::float8, f.trade_count,
                f.batch_id, f.loaded_at, f.extract_batch_id, f.source_file, m.sha256
                from dw.fact_ohlcv_hourly f
                join dw.dim_asset a using (asset_key) join dw.dim_source s using (source_key)
                left join meta.source_file_manifest m
                  on m.extract_batch_id=f.extract_batch_id and m.source_file=f.source_file
                where s.source_code='binance' and a.symbol='BTC'
                  and f.open_time >= %s and f.open_time < %s order by f.open_time''',
                (start.to_pydatetime(), end.to_pydatetime()))
            return pd.DataFrame(cursor.fetchall(), columns=[c.name for c in cursor.description])


def regression_metrics(actual, predicted, reference_close):
    actual, predicted, reference_close = (np.asarray(x, dtype=float) for x in (actual, predicted, reference_close))
    if not len(actual) or actual.shape != predicted.shape or actual.shape != reference_close.shape:
        raise ValueError('Metrics require non-empty aligned arrays')
    if not all(np.isfinite(x).all() for x in (actual, predicted, reference_close)):
        raise ValueError('Metrics cannot score non-finite values')
    mae = float(np.abs(predicted - actual).mean())
    baseline_mae = float(np.abs(actual).mean())
    price_error = np.abs(reference_close * np.expm1(predicted) - reference_close * np.expm1(actual))
    return {'n':len(actual), 'mae_log_return':mae,
            'relative_mae':mae / baseline_mae if baseline_mae > 0 else None,
            'rmse_log_return':float(np.sqrt(np.mean((predicted - actual) ** 2))),
            'mae_price_usdt':float(price_error.mean()),
            'directional_accuracy_pct':float((np.sign(actual) == np.sign(predicted)).mean() * 100)}


def paired_relative_ci(actual, predicted, target_times, repeats=500, block=24, seed=42):
    """Moving blocks within continuous target spans; paired model/baseline errors."""
    actual, predicted = np.asarray(actual), np.asarray(predicted)
    times = pd.DatetimeIndex(target_times)
    if len(actual) < block or len(actual) != len(predicted) or len(actual) != len(times):
        return None
    # Resample only continuous blocks; do not pretend a missing hour is adjacent.
    hour = pd.Timedelta(hours=1).value
    run_break = np.r_[0, np.cumsum(np.diff(times.asi8) != hour)]
    starts = np.flatnonzero(run_break[block-1:] == run_break[:len(times)-block+1])
    if not len(starts):
        return None
    rng = np.random.default_rng(seed)
    errors, zero_errors = np.abs(predicted - actual), np.abs(actual)
    ratios = []
    for _ in range(repeats):
        selected = rng.choice(starts, size=int(np.ceil(len(actual) / block)))
        index = (selected[:, None] + np.arange(block)).ravel()[:len(actual)]
        denominator = zero_errors[index].mean()
        if denominator > 0:
            ratios.append(errors[index].mean() / denominator)
    return np.quantile(ratios, [.025, .975]).tolist() if ratios else None


def goal_passed(metrics, threshold):
    ratio = metrics['relative_mae']
    return ratio is not None and np.isfinite(ratio) and ratio <= threshold


def summarize_predictions(predictions):
    result, monthly = {}, []
    methods = {'zero_return':'zero_log_return', 'mean24':'mean24_log_return', 'xgboost':'predicted_log_return'}
    for split, rows in predictions.groupby('split', sort=False):
        result[split] = {method:regression_metrics(rows.actual_log_return, rows[column], rows.reference_close_usdt)
                         for method, column in methods.items()}
        if split != 'train':
            result[split]['xgboost']['relative_mae_ci95'] = paired_relative_ci(
                rows.actual_log_return, rows.predicted_log_return, rows.target_open_time)
        for month, group in rows.groupby(rows.target_open_time.dt.strftime('%Y-%m')):
            for method, column in methods.items():
                monthly.append({'split':split, 'month':month, 'method':method,
                                **regression_metrics(group.actual_log_return, group[column], group.reference_close_usdt)})
    return result, monthly


def git_output(*args):
    return subprocess.check_output(['git', *args], text=True).strip()


def render_report(report, predictions, output):
    import plotly.graph_objects as go
    from plotly.offline import get_plotlyjs
    import plotly.io as pio
    def number(value, decimals=6):
        return '—' if value is None else f'{value:,.{decimals}f}'
    tables = []
    for split, methods in report['metrics'].items():
        rows = []
        for method, metrics in methods.items():
            rows.append(f'<tr><td>{escape(method)}</td><td>{metrics["n"]:,}</td>'
                        f'<td>{number(metrics["mae_log_return"])}</td><td>{number(metrics["relative_mae"],4)}</td>'
                        f'<td>{number(metrics["mae_price_usdt"],2)}</td><td>{number(metrics["directional_accuracy_pct"],2)}%</td></tr>')
        tables.append(f'<h3>{escape(split)}</h3><div class="scroll"><table><thead><tr>'
                      '<th>Phương pháp</th><th>Mẫu</th><th>MAE log-return ↓</th><th>Relative MAE ↓</th>'
                      '<th>MAE giá USDT ↓</th><th>Đúng hướng (phụ)</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>')
    month = pd.DataFrame(report['monthly_metrics'])
    month = month[(month['split'] != 'train') & (month.method == 'xgboost')]
    chart = go.Figure(go.Bar(x=month.month, y=month.relative_mae, marker_color=['#317355' if x == 'validation' else '#cc8b30' for x in month['split']]))
    chart.add_hline(y=1, line_dash='dash', annotation_text='Ngang zero-return')
    chart.add_hline(y=report['plan']['relative_mae_target'], line_dash='dot', annotation_text='Mục tiêu 0,95')
    chart.update_layout(title='Relative MAE theo tháng — chẩn đoán, không dùng tune test', yaxis_title='MAE model / MAE zero-return', template='plotly_white', height=440)
    scatter_rows = predictions[predictions['split'] == 'test']
    if len(scatter_rows) > 1200:
        scatter_rows = scatter_rows.sample(1200, random_state=42).sort_index()
    scatter = go.Figure(go.Scatter(x=scatter_rows.actual_log_return * 100, y=scatter_rows.predicted_log_return * 100,
                                  mode='markers', marker={'size':4, 'opacity':.4}))
    scatter.update_layout(title='Test hồi cứu: dự báo so với thực tế (tối đa 1.200 mẫu)', xaxis_title='Log-return thực tế × 100',
                          yaxis_title='Log-return dự báo × 100', template='plotly_white', height=440)
    plots = pio.to_html(chart, full_html=False, include_plotlyjs=False, config={'responsive':True}) + pio.to_html(scatter, full_html=False, include_plotlyjs=False, config={'responsive':True})
    test_metrics = report['metrics']['test']['xgboost']
    relative = test_metrics['relative_mae']
    improvement = (1-relative)*100 if relative is not None else None
    ci = test_metrics.get('relative_mae_ci95')
    grid = report['data_quality']
    checked = report.get('independent_checks')
    audit_text = (f'<p>Kiểm độc lập sau khi lưu model: <b>{checked["local_archives_verified"]} ZIP</b> khớp SHA-256 đã ghi; '
                  f'<b>{checked["facts_compared_to_zip"]:,} fact</b> khớp OHLC/volume/trade count trong ZIP. '
                  f'<b>{checked["prediction_rows_verified"]:,} dự báo</b> nạp lại và tái tính khớp tuyệt đối. '
                  'Không train lại trong bước kiểm này.</p>') if checked else ''
    body = f'''<header><h1>BTC giờ — XGBoost đầu tiên chạy thật</h1>
<p>Dự báo <b>ln(close giờ sau / close hiện tại)</b>. Không phải xác suất tăng, không có mua/bán tự động.</p>
<p><b>Baseline chính:</b> log-return = 0 → giá giờ sau bằng giá hiện tại.</p></header>
<section><h2>1. Definition of Done và mục tiêu</h2>
<p>Pipeline kỹ thuật: <b>COMPLETED</b> — snapshot → feature → train → validation → backtest → model có thể nạp lại.</p>
<p>Một metric chính: <b>Relative MAE ≤ {report['plan']['relative_mae_target']}</b> (giảm sai số ít nhất 5% so với zero-return).</p>
<p>Validation: <b>{escape(report['validation_decision'])}</b>. Test hồi cứu: <b>{escape(report['retrospective_test_decision'])}</b>.</p>
<p>Relative MAE test: <b>{number(relative,4)}</b>; giảm sai số so baseline: <b>{number(improvement,3)}%</b>.</p>
<p>CI bootstrap 95% của Relative MAE test: <b>{escape(str(ci))}</b>. Block 24 nến liên tục, 500 lần, seed 42; chỉ để mô tả bất định.</p>
<p class="warning"><b>Đây là backtest hồi cứu, không phải chứng nhận thành công trên test tương lai chưa xem.</b>
Năm 2026 đã xuất hiện trong EDA. Không thay feature/config sau khi đọc test của lần này để tuyên bố thắng trên cùng test.</p></section>
<section><h2>2. Dữ liệu và việc chống leakage</h2>
<ul><li>Nguồn: snapshot read-only PostgreSQL, BTC Binance Spot USDT 1h.</li>
<li>Khoảng: {escape(report['plan']['snapshot_start'])} → {escape(report['plan']['snapshot_end_exclusive'])}, end exclusive.</li>
<li>{grid['raw_rows']:,} nến thật; thiếu {grid['missing_hours']:,} giờ trên lưới; {grid['invalid_present_rows']:,} dòng hiện diện không hợp lệ.</li>
<li>{len(FEATURE_COLUMNS)} feature cố định; mỗi mẫu cần 169 nến đầu vào liên tục, cộng nến label đã đóng khi train.</li>
<li>Không fill nến thiếu; mẫu cắt gap/invalid/warmup bị loại và ghi lý do.</li>
<li>Chia theo target_open_time: train trước 2025; validation năm 2025; test từ 2026.</li>
<li>Early stopping chỉ nhìn validation; không search, không refit sau khi xem test.</li>
<li>Feature causal: không đọc nến sau cutoff. Không có scaler học trên toàn bộ dữ liệu.</li>
<li>Snapshot lịch sử có thể chứa chỉnh sửa sau này: chưa chứng minh dữ liệu point-in-time hoặc độ trễ nạp thật.</li></ul>
<p>Fact thiếu source checksum: {grid['facts_without_archive_checksum']:,}. Không tự suy ra lineage cho fact cũ.</p>
{audit_text}
<div class="scroll"><pre>{escape(json.dumps(report['split_counts'],ensure_ascii=False,indent=2))}</pre></div></section>
<section><h2>3. Cùng mẫu, cùng target, ba phương pháp</h2>
<p>Mean24 là baseline phụ: trung bình 24 log-return đã biết. Zero-return directional accuracy không có nghĩa đoán hướng ngẫu nhiên: sign(0)=0.</p>
{''.join(tables)}</section><section><h2>4. Backtest theo thời gian</h2>{plots}</section>
<section><h2>5. Đọc kết quả đúng phạm vi</h2>
<p>Không đạt 0,95 → model chưa đạt mục tiêu, dù chương trình chạy đúng. Không thay metric để gọi thành công.</p>
<p>Kết quả không phải PnL: chưa mô phỏng spread, phí, slippage, latency hay một chiến lược giao dịch.</p>
<p>Lần này chỉ train một candidate BTC; không tự promote, không thay model classifier ngày, không bật API/live forecast.</p>
<p>Model được lưu trước khi chấm test; nạp lại cho dự báo khớp: <b>{report['reload_verified']}</b>.</p>
<pre>make hourly-train
# Hoặc tái hiện đúng snapshot cũ:
# python -m scripts.train_hourly --snapshot {escape(report['snapshot_path'])}</pre>
<p>Artifact folder: <code>{escape(report['run_dir'])}</code>. Có model.ubj, snapshot.csv, plan.json, feature_names.json,
training_history.json, predictions.csv, monthly_metrics.csv, report.json và bản sao code.</p></section>
<footer>Run: {escape(report['run_id'])}<br>Snapshot SHA-256: {escape(report['snapshot_sha256'])}<br>
Model SHA-256: {escape(report['model_sha256'])}<br>Thời gian: {escape(report['created_at'])}</footer>'''
    html = '''<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CoinSight — BTC hourly backtest</title><style>
body{margin:0;background:#f0f4f0;color:#193c30;font:16px/1.75 system-ui}main{max-width:1120px;margin:auto;padding:24px}header,section{padding:24px;background:white;border:1px solid #d5e1d6;border-radius:12px;margin-bottom:20px}h1{line-height:1.3}.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;white-space:nowrap}td,th{padding:10px;border-bottom:1px solid #dde6dd;text-align:right}td:first-child,th:first-child{text-align:left}pre{overflow:auto;background:#f0f5f0;padding:16px}.warning{border-left:4px solid #cf8a28;padding-left:16px}code,footer{overflow-wrap:anywhere}footer{font-size:13px}@media(max-width:600px){main{padding:8px}header,section{padding:14px}}
</style><script>''' + get_plotlyjs() + '</script></head><body><main>' + body + '</main></body></html>'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding='utf-8')


def run_training(snapshot=None, database_url=DATABASE_URL, output_root=Path('data/models/hourly'),
                 report_output=Path('frontend/public/reports/hourly-backtest.html')):
    from xgboost import XGBRegressor
    settings = SETTINGS['hourly_forecast']
    started = time.monotonic()
    created_at = datetime.now(timezone.utc)
    end = pd.Timestamp(created_at).floor('D')  # Archive backfill excludes the current UTC day.
    start = utc(settings['snapshot_start'])
    if snapshot is None:
        frame = read_snapshot(database_url, start, end)
    else:
        frame = pd.read_csv(snapshot, float_precision='round_trip')
    frame['open_time'] = pd.to_datetime(frame.open_time, utc=True)
    if frame.empty or frame.open_time.min() < start or frame.open_time.max() >= end:
        raise ValueError('Snapshot empty or outside the requested closed archive period')
    if frame.open_time.min() != start or frame.open_time.max() != end - pd.Timedelta(hours=1):
        # CSV reproduction may intentionally end at an older closed boundary.
        if snapshot is None or frame.open_time.min() != start:
            raise ValueError('Snapshot lacks requested edge candles; complete backfill first')
        end = frame.open_time.max() + pd.Timedelta(hours=1)
    frame = frame.sort_values('open_time').reset_index(drop=True)
    features, meta, exclusions = build_dataset(frame)
    splits = chronological_split(meta, utc(settings['validation_start']), utc(settings['test_start']))
    for name, mask in splits.items():
        if int(mask.sum()) < 500:
            raise ValueError(f'Insufficient samples in {name}: need >= 500')
    run_id = str(uuid4())
    run_dir = Path(output_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    snapshot_path = run_dir / 'snapshot.csv'
    frame.to_csv(snapshot_path, index=False, float_format='%.17g', lineterminator='\n')
    # Train from the serialized snapshot, so replay uses exactly the same float values.
    frame = pd.read_csv(snapshot_path, float_precision='round_trip')
    frame['open_time'] = pd.to_datetime(frame.open_time, utc=True)
    features, meta, exclusions = build_dataset(frame)
    splits = chronological_split(meta, utc(settings['validation_start']), utc(settings['test_start']))
    plan = {'symbol':'BTC', 'feature_version':FEATURE_VERSION, 'feature_names':FEATURE_COLUMNS,
            'snapshot_start':start, 'snapshot_end_exclusive':end,
            'validation_start':utc(settings['validation_start']), 'test_start':utc(settings['test_start']),
            'test_status':'retrospective_already_explored_not_untouched_future_test',
            'primary_baseline':'zero_return', 'relative_mae_target':settings['relative_mae_target'],
            'model_config':settings['model'], 'selection':'single candidate; validation MAE early stopping only',
            'recorded_before_fit_at':datetime.now(timezone.utc), 'snapshot_sha256':sha256(snapshot_path)}
    write_json(run_dir / 'plan.json', plan)
    write_json(run_dir / 'feature_names.json', FEATURE_COLUMNS)
    code_hashes = {}
    for source in [Path(__file__), Path('pipeline/decision/hourly_features.py'), Path('pipeline/settings.yaml'),
                   Path('pipeline/settings.py'), Path('scripts/train_hourly.py'), Path('scripts/requirements-hourly.txt')]:
        destination = run_dir / 'code' / source.name
        destination.parent.mkdir(exist_ok=True)
        destination.write_bytes(source.read_bytes())
        code_hashes[str(source)] = sha256(source)
    provenance = {'git_commit':git_output('rev-parse', 'HEAD'), 'git_status':git_output('status', '--short'),
                  'code_sha256':code_hashes, 'versions':{name:importlib.metadata.version(name)
                  for name in ['xgboost', 'numpy', 'pandas', 'scikit-learn']}}
    write_json(run_dir / 'provenance.json', provenance)
    (run_dir / 'working_tree.diff').write_text(git_output('diff', '--binary', 'HEAD'), encoding='utf-8')
    model = XGBRegressor(**settings['model'])
    model.fit(features.loc[splits['train']], meta.loc[splits['train'], 'actual_log_return'],
              eval_set=[(features.loc[splits['validation']], meta.loc[splits['validation'], 'actual_log_return'])], verbose=False)
    model_path = run_dir / 'model.ubj'
    model.save_model(model_path)  # Freeze artifact before ANY test prediction/metric.
    write_json(run_dir / 'training_history.json', model.evals_result())
    best_iteration = int(model.best_iteration)
    frozen_model_sha = sha256(model_path)
    write_json(run_dir / 'candidate.json', {'model_sha256':frozen_model_sha, 'best_iteration':best_iteration,
                                          'frozen_before_test_at':datetime.now(timezone.utc)})
    reloaded = XGBRegressor()
    reloaded.load_model(model_path)
    predictions = meta.copy()
    predictions['context_start_time'] = predictions.input_open_time - pd.Timedelta(hours=168)
    predictions['predicted_log_return'] = np.nan
    predictions['split'] = ''
    predictions['zero_log_return'] = 0.0
    for name, mask in splits.items():
        values = model.predict(features.loc[mask], iteration_range=(0, best_iteration + 1))
        replay = reloaded.predict(features.loc[mask], iteration_range=(0, best_iteration + 1))
        if not np.array_equal(values, replay):
            raise ValueError('Model reload predictions differ')
        predictions.loc[mask, 'predicted_log_return'] = values
        predictions.loc[mask, 'split'] = name
    predictions['forecast_close_usdt'] = predictions.reference_close_usdt * np.exp(predictions.predicted_log_return)
    grid, _, raw_valid = prepare_grid(frame)
    # Full input batch lineage, not just the batch of the last candle.
    batch_values = grid.batch_id.to_numpy()
    positions = grid.index.get_indexer(predictions.index)
    predictions['input_batch_ids'] = [json.dumps(sorted({int(v) for v in batch_values[i-168:i+1]})) for i in positions]
    predictions['snapshot_sha256'] = sha256(snapshot_path)
    predictions.to_csv(run_dir / 'predictions.csv', index=False, float_format='%.17g')
    metrics, monthly = summarize_predictions(predictions)
    pd.DataFrame(monthly).to_csv(run_dir / 'monthly_metrics.csv', index=False)
    exclusions['split'] = np.where(exclusions.target_open_time < utc(settings['validation_start']), 'train',
                                  np.where(exclusions.target_open_time < utc(settings['test_start']), 'validation', 'test'))
    # Last grid row has no label yet, and lies at the exclusive snapshot boundary.
    exclusions = exclusions[exclusions.target_open_time < end]
    exclusions.to_csv(run_dir / 'sample_audit.csv', index=False)
    counts = {}
    for name, mask in splits.items():
        audit = exclusions[exclusions['split'] == name]
        counts[name] = {'accepted':int(mask.sum()), 'rejected':int(audit.reason.ne('accepted').sum()),
                        'first_target_open':meta.loc[mask, 'target_open_time'].min(),
                        'last_target_open':meta.loc[mask, 'target_open_time'].max(),
                        'reasons':audit.reason.value_counts().to_dict()}
    quality = {'raw_rows':len(frame), 'expected_hours':len(grid), 'missing_hours':len(grid)-len(frame),
               'invalid_present_rows':int((~raw_valid.loc[frame.open_time]).sum()),
               'facts_without_archive_checksum':int(frame.sha256.isna().sum())}
    report = {'run_id':run_id, 'run_dir':str(run_dir), 'created_at':created_at, 'plan':plan,
              'snapshot_path':str(snapshot_path), 'snapshot_sha256':sha256(snapshot_path),
              'model_sha256':frozen_model_sha, 'best_iteration':best_iteration, 'reload_verified':True,
              'technical_status':'completed', 'live_promotion':False,
              'validation_decision':'target_met' if goal_passed(metrics['validation']['xgboost'], settings['relative_mae_target']) else 'target_not_met',
              'retrospective_test_decision':'target_met' if goal_passed(metrics['test']['xgboost'], settings['relative_mae_target']) else 'target_not_met',
              'unseen_future_test_decision':'not_evaluated', 'data_quality':quality,
              'split_counts':counts, 'metrics':metrics, 'monthly_metrics':monthly,
              'source_batch_ids':sorted(frame.batch_id.unique().tolist()),
              'elapsed_seconds':time.monotonic()-started, 'provenance':provenance}
    write_json(run_dir / 'report.json', report)
    report = safe_json(report)
    render_report(report, predictions, Path(report_output))
    print(json.dumps({'run_id':run_id, 'run_dir':str(run_dir), 'report':str(report_output),
                      'best_iteration':best_iteration, 'data_quality':quality,
                      'validation':metrics['validation'], 'test':metrics['test'],
                      'validation_decision':report['validation_decision'],
                      'retrospective_test_decision':report['retrospective_test_decision'],
                      'elapsed_seconds':report['elapsed_seconds']}, ensure_ascii=False, indent=2))
    return report
