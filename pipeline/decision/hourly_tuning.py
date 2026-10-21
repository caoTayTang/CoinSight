"""Bounded, recorded XGBoost experiments using 2025 validation only.

2020-24 fit; Jan-Jun 2025 early stop; Jul-Dec 2025 candidate selection.
No 2026 rows are included in the experiment snapshot or prediction outputs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import importlib.metadata
import json
from pathlib import Path
import time
from uuid import uuid4

import numpy as np
import pandas as pd

from pipeline.decision.hourly_engineering import FEATURE_VERSION, build_experimental_inputs, feature_sets
from pipeline.decision.hourly_model import (git_output, regression_metrics, safe_json, sha256, utc, write_json)


VALIDATION_START = utc('2025-01-01')
SELECTION_START = utc('2025-07-01')
TEST_START = utc('2026-01-01')
TARGET = .95


def load_development_snapshot(path):
    """Filter by raw candle time BEFORE feature generation, labels or any scoring."""
    frames = []
    for chunk in pd.read_csv(path, float_precision='round_trip', chunksize=10000):
        chunk['open_time'] = pd.to_datetime(chunk.open_time, utc=True)
        frames.append(chunk[chunk.open_time < TEST_START])
    frame = pd.concat(frames, ignore_index=True)
    if frame.empty or frame.open_time.max() != TEST_START - pd.Timedelta(hours=1):
        raise ValueError('Need development history through 2025-12-31 23:00 UTC')
    return frame


def development_splits(meta):
    target = meta.target_open_time
    if (target >= TEST_START).any():
        raise ValueError('Test rows must not enter validation tuning')
    masks = {'train':target < VALIDATION_START,
             'early_stop':(target >= VALIDATION_START) & (target < SELECTION_START),
             'selection':(target >= SELECTION_START) & (target < TEST_START)}
    for name, mask in masks.items():
        if mask.sum() < 500:
            raise ValueError(f'Insufficient {name} samples')
    for left, right in [('train', 'early_stop'), ('early_stop', 'selection')]:
        if meta.loc[masks[left], 'target_close_time'].max() > meta.loc[masks[right], 'cutoff_time'].min():
            raise ValueError('Label timing crosses a decision boundary')
    return masks


def experiment_recipes(original_config):
    """Exactly 28 recipes fixed before results, not an adaptive test-driven search."""
    recipes = [{'name':'reference_v1', 'feature_set':'base', 'train_start':'2020-01-01',
                'target_transform':'raw', 'params':dict(original_config)}]
    common = {**original_config, 'n_estimators':800, 'early_stopping_rounds':50,
              'reg_alpha':0, 'gamma':0, 'base_score':0}
    for features in ['base', 'expanded', 'compact']:
        for objective in ['reg:squarederror', 'reg:absoluteerror']:
            for depth in [2, 4, 6]:
                recipes.append({'name':f'{features}_{"mse" if objective.endswith("squarederror") else "mae"}_d{depth}',
                                'feature_set':features, 'train_start':'2020-01-01', 'target_transform':'bps',
                                'params':{**common, 'objective':objective, 'max_depth':depth}})
    # Matched pruning experiments: only gamma changes within this three-trial group.
    for gamma in [0, 1000, 10000]:
        recipes.append({'name':f'prune_g{gamma}', 'feature_set':'expanded', 'train_start':'2020-01-01',
                        'target_transform':'bps', 'params':{**common, 'max_depth':6, 'min_child_weight':100,
                                                           'reg_lambda':50, 'gamma':gamma}})
    for year in [2023, 2024]:
        for objective in ['reg:squarederror', 'reg:absoluteerror']:
            recipes.append({'name':f'recent_{year}_{"mse" if objective.endswith("squarederror") else "mae"}',
                            'feature_set':'compact', 'train_start':f'{year}-01-01', 'target_transform':'bps',
                            'params':{**common, 'objective':objective, 'max_depth':3, 'min_child_weight':100}})
    for objective in ['reg:squarederror', 'reg:absoluteerror']:
        recipes.append({'name':f'volscaled_{"mse" if objective.endswith("squarederror") else "mae"}',
                        'feature_set':'compact', 'train_start':'2020-01-01', 'target_transform':'vol24',
                        'params':{**common, 'objective':objective, 'max_depth':3, 'min_child_weight':100}})
    assert len(recipes) == 28
    return recipes


def inverse_target_scale(transform, base_features):
    if transform == 'raw':
        return pd.Series(1., index=base_features.index)
    if transform == 'bps':
        return pd.Series(.0001, index=base_features.index)
    if transform == 'vol24':
        return base_features.return_std_24.clip(lower=.0001)
    raise ValueError(f'Unknown target transform: {transform}')


def model_tree_diagnostics(model):
    booster = model.get_booster()[:int(model.best_iteration)+1]
    trees = booster.trees_to_dataframe()
    leaves = trees[trees.Feature.eq('Leaf')]
    def depth(node):
        return 0 if 'leaf' in node else 1 + max(depth(child) for child in node['children'])
    depths = [depth(json.loads(tree)) for tree in booster.get_dump(dump_format='json')]
    return {'used_trees':booster.num_boosted_rounds(), 'stored_trees':model.get_booster().num_boosted_rounds(),
            'max_actual_depth':max(depths), 'mean_actual_depth':float(np.mean(depths)),
            'mean_leaves_per_tree':float(leaves.groupby('Tree').size().mean()),
            'split_count':int(trees.Feature.ne('Leaf').sum()),
            'total_gain':dict(sorted(booster.get_score(importance_type='total_gain').items(),
                                    key=lambda pair:pair[1], reverse=True))}


def prediction_diagnostics(actual, predicted):
    actual, predicted = np.asarray(actual), np.asarray(predicted)
    return {'actual_std':float(actual.std()), 'prediction_std':float(predicted.std()),
            'actual_abs_mean':float(np.abs(actual).mean()), 'prediction_abs_mean':float(np.abs(predicted).mean()),
            'correlation':float(np.corrcoef(actual, predicted)[0,1]) if np.std(predicted) > 0 else None}


def predict_raw(model, features, scale):
    return model.predict(features, iteration_range=(0, int(model.best_iteration)+1)) * np.asarray(scale)


def predict_candidate(run_dir, raw_candles):
    """Offline experimental inference on 169 closed candles; never needs a label.

    Not live publication: callers must handle freshness/ingestion/promotion separately.
    """
    from xgboost import XGBRegressor
    run_dir = Path(run_dir)
    recipe = json.loads((run_dir / 'selected_recipe.json').read_text())
    if sha256(run_dir / 'selected_model.ubj') != recipe['model_sha256']:
        raise ValueError('Selected model hash mismatch')
    sets = build_experimental_inputs(raw_candles)
    features = sets[recipe['feature_set']].iloc[[-1]]
    names = json.loads((run_dir / 'plan.json').read_text())['feature_names'][recipe['feature_set']]
    if list(features.columns) != names or features.isna().any().any():
        raise ValueError('Incomplete context or incompatible feature schema')
    scale = inverse_target_scale(recipe['target_transform'], sets['base']).iloc[[-1]]
    model = XGBRegressor(); model.load_model(run_dir / 'selected_model.ubj')
    predicted = float(predict_raw(model, features, scale)[0])
    return predicted


def block_permutation(model, features, actual, scale, repeats=3, seed=42, top=20):
    """Exploratory conditional-model diagnostic, not causal/independent feature proof."""
    gain = model.get_booster()[:int(model.best_iteration)+1].get_score(importance_type='total_gain')
    names = sorted(gain, key=gain.get, reverse=True)[:top]
    baseline = np.abs(predict_raw(model, features, scale) - np.asarray(actual)).mean()
    rng = np.random.default_rng(seed)
    blocks = [np.arange(i, min(i+24, len(features))) for i in range(0, len(features), 24)]
    rows = []
    for name in names:
        differences = []
        for _ in range(repeats):
            index = np.concatenate([blocks[i] for i in rng.permutation(len(blocks))])
            perturbed = features.copy()
            perturbed[name] = features[name].to_numpy()[index]
            differences.append(float(np.abs(predict_raw(model, perturbed, scale) - np.asarray(actual)).mean() - baseline))
        rows.append({'feature':name, 'mae_increase_when_permuted':float(np.mean(differences)),
                     'repeat_values':differences})
    return sorted(rows, key=lambda row:row['mae_increase_when_permuted'], reverse=True)


def render_tuning(report, output):
    import plotly.graph_objects as go
    from plotly.offline import get_plotlyjs
    import plotly.io as pio
    results = pd.DataFrame(report['trials'])
    results = results.sort_values('selection_relative_mae')
    columns = ['name', 'feature_set', 'n_features', 'objective', 'max_depth', 'min_child_weight',
               'reg_lambda', 'gamma', 'train_start', 'target_transform', 'best_trees',
               'train_relative_mae', 'early_stop_relative_mae', 'selection_relative_mae']
    table = results[columns].to_html(index=False, escape=True, float_format=lambda x:f'{x:.6f}')
    best = report['winner']
    original = report['original_diagnostics']
    chart = go.Figure()
    for field, label in [('early_stop_relative_mae','Early stop Jan–Jun'), ('selection_relative_mae','Selection Jul–Dec')]:
        chart.add_trace(go.Bar(x=results.name, y=results[field], name=label))
    chart.add_hline(y=1, line_dash='dash', annotation_text='Zero-return = 1')
    chart.add_hline(y=TARGET, line_dash='dot', annotation_text='Mục tiêu = 0,95')
    chart.update_layout(title='28 candidate — chọn bằng Jul–Dec 2025, không dùng test', template='plotly_white',
                        height=550, yaxis_title='Relative MAE ↓', barmode='group', xaxis_tickangle=-55)
    chart2 = go.Figure()
    monthly = pd.DataFrame(report['monthly'])
    for method, rows in monthly.groupby('method', sort=False):
        chart2.add_trace(go.Scatter(x=rows.month, y=rows.relative_mae, name=method, mode='lines+markers'))
    chart2.add_hline(y=1, line_dash='dash')
    chart2.update_layout(title='Theo tháng validation — winner, reference refit và zero', template='plotly_white',
                         height=420, yaxis_title='Relative MAE ↓')
    plots = ''.join(pio.to_html(fig, full_html=False, include_plotlyjs=False, config={'responsive':True}) for fig in [chart, chart2])
    permutation = pd.DataFrame(report['winner_permutation_importance'])
    permutation = permutation.drop(columns=['repeat_values']).to_html(index=False, escape=True, float_format=lambda x:f'{x:.9f}')
    gain = pd.DataFrame(list(original['trees']['total_gain'].items())[:15], columns=['Feature', 'Training total gain'])
    gain_html = gain.to_html(index=False, escape=True)
    body = f'''<header><h1>XGBoost: nhìn bên trong, rồi tune bằng validation</h1>
<p>BTC 1h, target không đổi: ln(close giờ sau / close hiện tại). Baseline zero-return. Mục tiêu Relative MAE ≤ 0,95.</p>
<p><b>Không chấm lại 2026.</b> Snapshot tuning chỉ có nến trước 2026-01-01 UTC.</p></header>
<section><h2>1. Model đầu thực sự học gì?</h2>
<p>max_depth=3; min_child_weight=20; lambda=10; alpha=0; gamma=0; learning_rate=0,03.</p>
<p>{original['trees']['used_trees']} cây được dùng, độ sâu thực tối đa {original['trees']['max_actual_depth']},
trung bình {original['trees']['mean_leaves_per_tree']:.2f} lá/cây.</p>
<p>Validation 2025: std log-return thực tế {original['predictions']['actual_std']:.6f}; std dự báo {original['predictions']['prediction_std']:.6f}.
Dự báo co gần 0. Điều này chưa phân biệt được regularization quá mạnh với tín hiệu đầu vào yếu.</p>
<p>Gamma=0 nghĩa là chưa áp ngưỡng gain dương thêm cho pruning. Không nên mặc định pruning mạnh hơn sẽ chữa được model gần-zero.</p>
<h3>Feature được cây dùng — chỉ phản ánh training gain</h3><div class="scroll">{gain_html}</div></section>
<section><h2>2. Thiết kế tuning</h2>
<ul><li>Train: 2020–2024. Early stopping: Jan–Jun 2025. Chọn candidate: Jul–Dec 2025.</li>
<li>28 recipe ghi vào plan.json trước fit; không adaptive search sau khi thấy điểm.</li>
<li>So depth 2/4/6, loss squared-error/absolute-error, feature base/expanded/compact.</li>
<li>Pruning matched: depth 6, min_child=100, lambda=50; gamma 0/1000/10000 khi target tính theo bps.</li>
<li>Thử train gần hơn (2023 hoặc 2024) và target chuẩn hóa bằng volatility đã biết.</li>
<li>MAE chọn candidate luôn tính lại trên log-return gốc. Thay đơn vị target không thay metric.</li>
<li>Target volscaled có sample weights để loss/early stopping vẫn tương ứng sai số gốc.</li>
<li>Không tự fill gap, không dùng tương lai, không thêm nguồn ngoài OHLCV/trade count.</li></ul>
<p><b>2025 là validation đã được xem và dùng chọn trong nhiều lần thử.</b> Điểm winner có selection optimism, không phải kết quả test chưa xem.</p>
<p>Snapshot tuning SHA-256: <code>{escape(report['snapshot_sha256'])}</code></p></section>
<section><h2>3. Kết quả chọn candidate</h2>
<p>Winner: <b>{escape(best['name'])}</b>, feature <b>{escape(best['feature_set'])}</b>, objective <b>{escape(best['objective'])}</b>, max_depth <b>{best['max_depth']}</b>.</p>
<p>Relative MAE Jul–Dec: <b>{best['selection_relative_mae']:.6f}</b>; giảm sai số so zero-return <b>{(1-best['selection_relative_mae'])*100:.3f}%</b>.</p>
<p>Trạng thái mục tiêu validation: <b>{escape(report['validation_target_status'])}</b>. Test: <b>NOT EVALUATED</b>. Live promotion: <b>NO</b>.</p>
<p>Reference trong bảng được train lại cùng early-stop Jan–Jun. Model cũ đã chọn vòng theo cả 2025 nên không được lấy nó làm đối chứng chưa dùng Jul–Dec.</p>
<div class="scroll">{table}</div>{plots}</section>
<section><h2>4. Feature engineering đã thử, không chỉ đoán</h2>
<p>Expanded bổ sung momentum chuẩn hóa volatility, mean/median return, khoảng cách tới giá trung bình/đỉnh/đáy,
RSI rolling, tỷ lệ volatility, volume có dấu nến (chỉ là proxy, không phải order flow), volume/trade count tương đối.</p>
<p>Compact bỏ các sparse lag và giữ feature hiện tại + thống kê nhân quả. Tất cả vẫn chỉ dùng tối đa 169 nến gốc.</p>
<p>Permutation dưới đây đo mức tăng MAE khi đảo block 24 giờ của từng feature top-gain, 3 lần, chỉ trên selection validation.
Feature tương quan có thể thay thế nhau; đây không phải bằng chứng nhân quả hoặc test độc lập.</p>
<div class="scroll">{permutation}</div></section>
<section><h2>5. Artifact và bước tiếp</h2>
<p>Run: <code>{escape(report['run_dir'])}</code>. Mỗi trial có model, config, curves, feature names, predictions validation.
Winner được nạp lại và dự báo khớp: <b>{report['winner_reload_verified']}</b>.</p>
<p>Không ghi đè candidate ban đầu. Không gọi việc tune là thắng nếu Relative MAE chưa xuống 0,95.
Sau khi khóa recipe, cần kỳ tương lai mới cho đánh giá cuối. Không chỉnh theo test 2026 đã xem.</p></section>'''
    html = '''<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CoinSight — XGBoost validation tuning</title><style>
body{margin:0;background:#f1f5f1;color:#193c30;font:16px/1.75 system-ui}main{max-width:1150px;margin:auto;padding:24px}header,section{background:white;padding:24px;border:1px solid #d5e1d6;border-radius:12px;margin-bottom:20px}.scroll{overflow-x:auto}table{border-collapse:collapse;white-space:nowrap;width:100%}td,th{padding:9px;border-bottom:1px solid #dde6dd;text-align:right}td:first-child,th:first-child{text-align:left}h1{line-height:1.3}code{overflow-wrap:anywhere}@media(max-width:600px){main{padding:8px}header,section{padding:14px}}
</style><script>''' + get_plotlyjs() + '</script></head><body><main>' + body + '</main></body></html>'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding='utf-8')


def run_tuning(base_run, output_root=Path('data/models/hourly-tuning'),
               html_output=Path('frontend/public/reports/hourly-tuning.html')):
    from xgboost import XGBRegressor
    started = time.monotonic()
    base_run = Path(base_run)
    source_plan = json.loads((base_run / 'plan.json').read_text())
    if sha256(base_run / 'snapshot.csv') != source_plan['snapshot_sha256']:
        raise ValueError('Base snapshot hash mismatch')
    recipes = experiment_recipes(source_plan['model_config'])
    frame = load_development_snapshot(base_run / 'snapshot.csv')
    run_dir = Path(output_root) / str(uuid4())
    run_dir.mkdir(parents=True, exist_ok=False)
    snapshot = run_dir / 'development_snapshot.csv'
    frame.to_csv(snapshot, index=False, float_format='%.17g')
    sets, meta, audit = feature_sets(frame)
    splits = development_splits(meta)
    plan = {'created_before_fit_at':datetime.now(timezone.utc), 'base_run':str(base_run),
            'snapshot_sha256':sha256(snapshot), 'feature_version':FEATURE_VERSION,
            'feature_names':{name:list(features.columns) for name,features in sets.items()},
            'validation_start':VALIDATION_START, 'selection_start':SELECTION_START, 'test_start':TEST_START,
            'test_scoring':False, 'relative_mae_target':TARGET, 'recipes':recipes,
            'selection_metric':'raw log-return MAE on Jul-Dec 2025 only',
            'target_weighting':'vol24: train weight scale^2 for MSE or scale for MAE, normalized to mean 1; eval weight scale',
            'split_counts':{name:int(mask.sum()) for name,mask in splits.items()}}
    write_json(run_dir / 'plan.json', plan)
    audit.loc[audit.target_open_time < TEST_START].to_csv(run_dir / 'sample_audit.csv', index=False)
    provenance = {'git_commit':git_output('rev-parse', 'HEAD'), 'git_status':git_output('status', '--short'),
                  'versions':{name:importlib.metadata.version(name) for name in ['xgboost','numpy','pandas','scikit-learn']},
                  'code_sha256':{}}
    for source in [Path(__file__), Path('pipeline/decision/hourly_engineering.py'),
                   Path('pipeline/decision/hourly_features.py'), Path('pipeline/decision/hourly_model.py'),
                   Path('scripts/tune_hourly.py'), Path('scripts/requirements-hourly.txt')]:
        destination = run_dir / 'code' / source.name
        destination.parent.mkdir(exist_ok=True)
        destination.write_bytes(source.read_bytes())
        provenance['code_sha256'][str(source)] = sha256(source)
    write_json(run_dir / 'provenance.json', provenance)
    original = XGBRegressor(); original.load_model(base_run / 'model.ubj')
    val = splits['early_stop'] | splits['selection']
    original_predictions = predict_raw(original, sets['base'].loc[val], np.ones(int(val.sum())))
    original_diagnostics = {'params':source_plan['model_config'], 'trees':model_tree_diagnostics(original),
                            'predictions':prediction_diagnostics(meta.loc[val,'actual_log_return'], original_predictions)}
    write_json(run_dir / 'original_diagnostics.json', original_diagnostics)
    rows, validation_predictions = [], {}
    for number, recipe in enumerate(recipes, 1):
        trial_started = time.monotonic()
        trial_dir = run_dir / recipe['name']; trial_dir.mkdir()
        features = sets[recipe['feature_set']]
        scale = inverse_target_scale(recipe['target_transform'], sets['base'])
        train = splits['train'] & meta.target_open_time.ge(utc(recipe['train_start']))
        stop = splits['early_stop']; select = splits['selection']
        if train.sum() < 500:
            raise ValueError('Training window too short')
        y = meta.actual_log_return / scale
        power = 1 if recipe['params']['objective'] == 'reg:absoluteerror' else 2
        weights = scale.loc[train] ** power
        weights /= weights.mean()
        eval_weights = scale.loc[stop] / scale.loc[stop].mean()
        write_json(trial_dir / 'config.json', recipe)
        write_json(trial_dir / 'feature_names.json', list(features.columns))
        model = XGBRegressor(**recipe['params'])
        model.fit(features.loc[train], y.loc[train], sample_weight=weights,
                  eval_set=[(features.loc[stop], y.loc[stop])], sample_weight_eval_set=[eval_weights], verbose=False)
        model.save_model(trial_dir / 'model.ubj')
        write_json(trial_dir / 'training_history.json', model.evals_result())
        trial_predictions = meta.loc[val].copy()
        trial_predictions['partition'] = np.where(stop.loc[val], 'early_stop', 'selection')
        trial_predictions['predicted_log_return'] = predict_raw(model, features.loc[val], scale.loc[val])
        trial_predictions.to_csv(trial_dir / 'validation_predictions.csv', index=False, float_format='%.17g')
        validation_predictions[recipe['name']] = trial_predictions
        metrics = {}
        for name, mask in [('train',train), ('early_stop',stop), ('selection',select)]:
            predicted = predict_raw(model, features.loc[mask], scale.loc[mask])
            metrics[name] = regression_metrics(meta.loc[mask,'actual_log_return'], predicted, meta.loc[mask,'reference_close_usdt'])
        row = {'name':recipe['name'], 'feature_set':recipe['feature_set'], 'n_features':features.shape[1],
               'objective':recipe['params']['objective'], 'max_depth':recipe['params']['max_depth'],
               'gamma':recipe['params'].get('gamma',0), 'min_child_weight':recipe['params']['min_child_weight'],
               'reg_lambda':recipe['params']['reg_lambda'], 'train_start':recipe['train_start'],
               'target_transform':recipe['target_transform'], 'train_n':int(train.sum()),
               'best_trees':int(model.best_iteration)+1, 'model_sha256':sha256(trial_dir / 'model.ubj'),
               'train_relative_mae':metrics['train']['relative_mae'],
               'early_stop_relative_mae':metrics['early_stop']['relative_mae'],
               'selection_relative_mae':metrics['selection']['relative_mae'],
               'selection_mae':metrics['selection']['mae_log_return'],
               'selection_diagnostics':prediction_diagnostics(meta.loc[select,'actual_log_return'],
                                                              trial_predictions.loc[select,'predicted_log_return']),
               'elapsed_seconds':time.monotonic()-trial_started}
        write_json(trial_dir / 'metrics.json', {'summary':row, 'metrics':metrics})
        rows.append(row)
        write_json(run_dir / 'trial_results.json', rows)
        print(f'[{number}/{len(recipes)}] {recipe["name"]}: train={row["train_relative_mae"]:.6f}, '
              f'stop={row["early_stop_relative_mae"]:.6f}, select={row["selection_relative_mae"]:.6f}, trees={row["best_trees"]}', flush=True)
    winner = min(rows, key=lambda row:(row['selection_mae'], row['name']))
    winner_recipe = next(recipe for recipe in recipes if recipe['name'] == winner['name'])
    winner_dir = run_dir / winner['name']
    model = XGBRegressor(); model.load_model(winner_dir / 'model.ubj')
    features = sets[winner['feature_set']]
    scale = inverse_target_scale(winner_recipe['target_transform'], sets['base'])
    replay = predict_raw(model, features.loc[val], scale.loc[val])
    np.testing.assert_array_equal(replay, validation_predictions[winner['name']].predicted_log_return.to_numpy())
    permutation = block_permutation(model, features.loc[select], meta.loc[select,'actual_log_return'], scale.loc[select])
    monthly = []
    for name in ['reference_v1', winner['name']]:
        predicted = validation_predictions[name]
        for month, group in predicted.groupby(predicted.target_open_time.dt.strftime('%Y-%m')):
            monthly.append({'method':name, 'month':month,
                            **regression_metrics(group.actual_log_return, group.predicted_log_return, group.reference_close_usdt)})
    for month, group in meta.loc[val].groupby(meta.loc[val,'target_open_time'].dt.strftime('%Y-%m')):
        monthly.append({'method':'zero_return', 'month':month,
                        **regression_metrics(group.actual_log_return, np.zeros(len(group)), group.reference_close_usdt)})
    pd.DataFrame(rows).drop(columns=['selection_diagnostics']).to_csv(run_dir / 'leaderboard.csv', index=False)
    report = {'run_dir':str(run_dir), 'created_at':datetime.now(timezone.utc), 'plan':plan,
              'snapshot_sha256':sha256(snapshot), 'snapshot_max_raw_open_time':frame.open_time.max(),
              'test_rows_used':0, 'test_metrics':None, 'live_promotion':False,
              'winner':winner, 'winner_recipe':winner_recipe, 'winner_reload_verified':True,
              'winner_tree_diagnostics':model_tree_diagnostics(model),
              'winner_permutation_importance':permutation, 'original_diagnostics':original_diagnostics,
              'validation_target_status':'target_met' if winner['selection_relative_mae'] <= TARGET else 'target_not_met',
              'trials':rows, 'monthly':monthly, 'elapsed_seconds':time.monotonic()-started}
    write_json(run_dir / 'report.json', report)
    (run_dir / 'selected_model.ubj').write_bytes((winner_dir / 'model.ubj').read_bytes())
    write_json(run_dir / 'selected_recipe.json', {**winner_recipe, 'best_trees':winner['best_trees'],
                                               'model_sha256':winner['model_sha256'], 'test_status':'not_evaluated'})
    render_tuning(safe_json(report), Path(html_output))
    print(json.dumps(safe_json({'run_dir':str(run_dir), 'html':str(html_output), 'winner':winner,
                                'validation_target_status':report['validation_target_status'], 'test_rows_used':0,
                                'elapsed_seconds':report['elapsed_seconds']}), ensure_ascii=False, indent=2), flush=True)
    return report
