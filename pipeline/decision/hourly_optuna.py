"""Seeded Optuna on development data only, plus controlled data/label diagnostics.

2025 Jan-Jun early stopping; Jul-Dec objective. No 2026 dataset or scoring.
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

from pipeline.decision.hourly_engineering import feature_sets
from pipeline.decision.hourly_model import git_output, regression_metrics, safe_json, sha256, utc, write_json
from pipeline.decision.hourly_tuning import (TEST_START, TARGET, development_splits, model_tree_diagnostics,
                                           predict_candidate, predict_raw)


TRAIN_STARTS = ['2020-01-01', '2022-01-01', '2023-01-01', '2024-01-01', '2024-07-01']


def search_recipe(trial, base_params):
    objective = trial.suggest_categorical('objective', ['reg:absoluteerror', 'reg:squarederror'])
    gamma_name = 'gamma_mae' if objective == 'reg:absoluteerror' else 'gamma_mse'
    gammas = [0., 1., 5., 20.] if objective == 'reg:absoluteerror' else [0., 100., 1000., 10000.]
    return {'name':f'trial_{trial.number:03d}',
            'feature_set':trial.suggest_categorical('feature_set', ['compact', 'base', 'expanded']),
            'train_start':trial.suggest_categorical('train_start', TRAIN_STARTS), 'target_transform':'bps',
            'params':{**base_params, 'objective':objective, 'n_estimators':1200, 'early_stopping_rounds':50,
                      'max_depth':trial.suggest_int('max_depth', 1, 6),
                      'learning_rate':trial.suggest_float('learning_rate', .01, .1, log=True),
                      'min_child_weight':trial.suggest_int('min_child_weight', 20, 300, log=True),
                      'reg_lambda':trial.suggest_float('reg_lambda', .1, 100, log=True),
                      'reg_alpha':trial.suggest_categorical('reg_alpha', [0., .1, 1., 10.]),
                      'gamma':trial.suggest_categorical(gamma_name, gammas),
                      'subsample':trial.suggest_float('subsample', .6, 1.),
                      'colsample_bytree':trial.suggest_float('colsample_bytree', .5, 1.),
                      'random_state':42, 'n_jobs':2}}


def block_shuffle(values, seed, block=24):
    """Training labels only; keep within-block serial order, break feature alignment."""
    values = np.asarray(values)
    blocks = [np.arange(i, min(i+block, len(values))) for i in range(0, len(values), block)]
    order = np.random.default_rng(seed).permutation(len(blocks))
    return values[np.concatenate([blocks[i] for i in order])]


def fit_recipe(recipe, sets, meta, masks, directory, shuffle_seed=None):
    from xgboost import XGBRegressor
    started = time.monotonic()
    directory.mkdir(parents=True, exist_ok=False)
    features = sets[recipe['feature_set']]
    train = masks['train'] & meta.target_open_time.ge(utc(recipe['train_start']))
    stop, select = masks['early_stop'], masks['selection']
    if train.sum() < 500:
        raise ValueError('Too few training samples')
    # Fixed basis-point units: predict raw log-return * 10,000, then invert.
    target = meta.actual_log_return * 10000
    y_train = target.loc[train].to_numpy()
    if shuffle_seed is not None:
        y_train = block_shuffle(y_train, shuffle_seed)
    write_json(directory / 'config.json', {**recipe, 'shuffle_seed':shuffle_seed})
    write_json(directory / 'feature_names.json', list(features.columns))
    model = XGBRegressor(**recipe['params'])
    model.fit(features.loc[train], y_train, eval_set=[(features.loc[stop], target.loc[stop])], verbose=False)
    model.save_model(directory / 'model.ubj')
    write_json(directory / 'training_history.json', model.evals_result())
    validation = meta.loc[stop | select].copy()
    validation['partition'] = np.where(stop.loc[validation.index], 'early_stop', 'selection')
    validation['predicted_log_return'] = predict_raw(model, features.loc[validation.index], np.full(len(validation), .0001))
    validation.to_csv(directory / 'validation_predictions.csv', index=False, float_format='%.17g')
    metrics = {}
    for name, mask in [('train', train), ('early_stop', stop), ('selection', select)]:
        predicted = predict_raw(model, features.loc[mask], np.full(int(mask.sum()), .0001))
        metrics[name] = regression_metrics(meta.loc[mask,'actual_log_return'], predicted, meta.loc[mask,'reference_close_usdt'])
    # A separate direction-only reference learned on TRAIN; not the regression baseline.
    majority_sign = 1 if (meta.loc[train,'actual_log_return'] > 0).mean() >= .5 else -1
    direction_reference = float((np.sign(meta.loc[select,'actual_log_return']) == majority_sign).mean()*100)
    summary = {'name':recipe['name'], 'feature_set':recipe['feature_set'], 'n_features':features.shape[1],
               'train_start':recipe['train_start'], 'train_n':int(train.sum()),
               'objective':recipe['params']['objective'], 'max_depth':recipe['params']['max_depth'],
               'best_trees':int(model.best_iteration)+1,
               'train_relative_mae':metrics['train']['relative_mae'],
               'early_stop_relative_mae':metrics['early_stop']['relative_mae'],
               'selection_relative_mae':metrics['selection']['relative_mae'],
               'selection_mae':metrics['selection']['mae_log_return'],
               'selection_directional_accuracy_pct':metrics['selection']['directional_accuracy_pct'],
               'selection_majority_direction_reference_pct':direction_reference,
               'majority_sign_from_train':majority_sign,
               'model_sha256':sha256(directory / 'model.ubj'), 'shuffle_seed':shuffle_seed,
               'elapsed_seconds':time.monotonic()-started}
    write_json(directory / 'metrics.json', {'summary':summary, 'metrics':metrics})
    return summary, model, validation


def render_optuna(report, output):
    import plotly.graph_objects as go
    from plotly.offline import get_plotlyjs
    import plotly.io as pio
    best = report['best']
    trials = pd.DataFrame(report['trials']).sort_values('selection_mae')
    history = pd.DataFrame(report['history_controls']).sort_values('train_n')
    negative = pd.DataFrame(report['label_controls'])
    figure = go.Figure()
    figure.add_trace(go.Scatter(x=history.train_n, y=history.train_relative_mae, name='Train', mode='lines+markers'))
    figure.add_trace(go.Scatter(x=history.train_n, y=history.selection_relative_mae, name='Selection Jul–Dec', mode='lines+markers',
                               text=history.train_start))
    figure.add_hline(y=1, line_dash='dash')
    figure.update_layout(title='Cùng cấu hình, thay lịch sử train — thêm năm cũ có giúp không?', template='plotly_white',
                         xaxis_title='Số mẫu train (thời gian, không random)', yaxis_title='Relative MAE ↓', height=430)
    search = pd.DataFrame(report['trials']).sort_values('number')
    figure2 = go.Figure(go.Scatter(x=search.number, y=search.selection_relative_mae, mode='markers', name='Trial'))
    figure2.add_trace(go.Scatter(x=search.number, y=search.selection_relative_mae.cummin(), mode='lines', name='Best so far'))
    figure2.add_hline(y=1, line_dash='dash')
    figure2.update_layout(title='Optuna TPE — điểm validation, không phải test', template='plotly_white', height=410,
                          xaxis_title='Trial', yaxis_title='Relative MAE ↓')
    plots = ''.join(pio.to_html(fig, include_plotlyjs=False, full_html=False, config={'responsive':True}) for fig in [figure2, figure])
    def table(frame, columns):
        return '<div class="scroll">' + frame[columns].to_html(index=False, escape=True, float_format=lambda value:f'{value:.6f}') + '</div>'
    leaderboard = table(trials,['number','feature_set','train_start','max_depth','objective','best_trees',
                              'train_relative_mae','early_stop_relative_mae','selection_relative_mae','selection_directional_accuracy_pct'])
    history_table = table(history,['train_start','train_n','train_relative_mae','early_stop_relative_mae','selection_relative_mae'])
    null_table = table(negative,['shuffle_seed','selection_relative_mae','selection_directional_accuracy_pct'])
    body = f'''<header><h1>Optuna và chẩn đoán BTC 1h</h1><p>Dự báo log-return giờ kế tiếp. Baseline chính = return 0.
<b>Không dùng dữ liệu 2026.</b> Mọi kết quả dưới đây là validation đã dùng để lựa chọn.</p></header>
<section><h2>1. Kết quả, không đổi thước đo</h2>
<p>{len(trials)} trial Optuna TPE, seed 42, chạy tuần tự; CPU hist, 2 threads. Thời gian cả search và diagnostics: {report['elapsed_seconds']:.1f} giây.</p>
<p>Best Relative MAE Jul–Dec 2025: <b>{best['selection_relative_mae']:.6f}</b> → giảm lỗi <b>{(1-best['selection_relative_mae'])*100:.3f}%</b> so zero-return.
Mục tiêu 0,95: <b>{escape(report['validation_target_status'])}</b>. Test mới: <b>NOT EVALUATED</b>.</p>
<p>Directional accuracy cùng đoạn: <b>{best['selection_directional_accuracy_pct']:.2f}%</b>;
reference hướng phổ biến học từ train: <b>{best['selection_majority_direction_reference_pct']:.2f}%</b>.
Đây là metric phụ; zero-return không phải “luôn tăng”.</p>
<p>MAE <code>0,004</code> không phải accuracy 99,6%: nó là sai số log-return, gần 0,4 điểm phần trăm khi biến động nhỏ.
Relative MAE cũng không phải accuracy. Không chấm lại 2026 hoặc tự promote.</p></section>
<section><h2>2. Search có kiểm soát</h2>
<ul><li>Train trước 2025; Jan–Jun 2025 early stopping; Jul–Dec 2025 objective.</li>
<li>Max depth 1–6; learning rate 0,01–0,1; min_child_weight 20–300; lambda 0,1–100; alpha 0/0,1/1/10.</li>
<li>Tune subsample, colsample, gamma theo objective, loss MAE/MSE, feature set và cửa sổ train.</li>
<li>Target dùng bps để gamma/alpha có đơn vị rõ; metric luôn đổi về log-return gốc.</li>
<li>Ngân sách/sampler/search space ghi trước vào plan.json; study SQLite giữ toàn bộ lịch sử.</li>
<li>Early stopping XGBoost, không Optuna-prune trial bằng một đoạn validation khác.</li></ul>
<p>Validation đã được dùng nhiều lần. TPE tối ưu hóa chính đoạn này, có selection optimism; không gọi điểm best là hiệu quả ngoài mẫu.</p>
<pre>{escape(json.dumps(report['best_recipe'],ensure_ascii=False,indent=2))}</pre>{plots}{leaderboard}</section>
<section><h2>3. Có phải thiếu dữ liệu?</h2>
<p>Đối chứng giữ nguyên recipe của winner 28-trial trước, chỉ thay năm bắt đầu train.
Không so hai model khác cả depth, loss lẫn feature để quy hết cho lượng data.</p>{history_table}
<p>Số mẫu và độ gần hiện tại thay đổi cùng nhau: đây là chẩn đoán history/regime, không tách riêng hoàn toàn ảnh hưởng sample size.
Các cửa sổ feature chồng lấn nên mẫu không độc lập như các ảnh ngẫu nhiên. Không có ngưỡng số mẫu chung bảo đảm dự báo được return.</p></section>
<section><h2>4. Negative control: phá liên kết feature–label trong train</h2>
<p>5 lần đảo block label 24 giờ, vẫn giữ validation thật, cùng recipe trước search. Không shuffle validation.
Nếu kết quả gần model thật, cần nghi ngờ tín hiệu yếu/bias; nếu kém hơn, chỉ là chẩn đoán hỗ trợ.</p>{null_table}
<p>Đây <b>không phải permutation p-value</b>: model thật đã được chọn qua nhiều trial; 5 control không lặp lại toàn search budget.
Không suy ra bằng chứng thống kê mạnh hoặc lợi nhuận từ bảng này.</p></section>
<section><h2>5. Artifact</h2><p><code>{escape(report['run_dir'])}</code>: study.sqlite3, plan, từng model/trial, curves,
validation predictions, leaderboard, controls và selected_model.ubj. Reload khớp: <b>{report['reload_verified']}</b>.
Suy luận bằng 169 nến, không cần label tương lai, đã kiểm: <b>{report['inference_without_target_verified']}</b>.</p>
<p>Chưa backfill thêm hoặc đổi coin. Nếu “ADA” là Cardano, cần dataset/model riêng; nếu là AdaBoost, đó là một candidate khác chứ không đảm bảo chữa được tín hiệu yếu.</p></section>'''
    html = '''<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CoinSight — Optuna & diagnostics</title><style>
body{margin:0;background:#f1f5f1;color:#193c30;font:16px/1.75 system-ui}main{max-width:1160px;margin:auto;padding:24px}section,header{background:white;padding:24px;border:1px solid #d5e1d6;border-radius:12px;margin-bottom:20px}.scroll,pre{overflow-x:auto}table{border-collapse:collapse;white-space:nowrap;width:100%}td,th{padding:9px;border-bottom:1px solid #dde6dd;text-align:right}td:first-child,th:first-child{text-align:left}pre{background:#f0f5ef;padding:16px}code{overflow-wrap:anywhere}h1{line-height:1.3}@media(max-width:600px){main{padding:8px}section,header{padding:14px}}
</style><script>''' + get_plotlyjs() + '</script></head><body><main>' + body + '</main></body></html>'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(html,encoding='utf-8')


def run_optuna(base_tuning, trials=50, output_root=Path('data/models/hourly-optuna'),
               html_output=Path('frontend/public/reports/hourly-optuna.html')):
    if trials < 1 or trials > 200:
        raise ValueError('Bounded trial count required: 1..200')
    import optuna
    from xgboost import XGBRegressor
    started = time.monotonic()
    base_tuning = Path(base_tuning)
    previous = json.loads((base_tuning/'report.json').read_text())
    source = base_tuning/'development_snapshot.csv'
    if sha256(source) != previous['snapshot_sha256']:
        raise ValueError('Development snapshot checksum mismatch')
    frame = pd.read_csv(source,float_precision='round_trip')
    frame['open_time'] = pd.to_datetime(frame.open_time,utc=True)
    if (frame.open_time >= TEST_START).any():
        raise ValueError('2026 candles are forbidden in Optuna dataset')
    sets, meta, audit = feature_sets(frame)
    masks = development_splits(meta)
    run_dir = Path(output_root)/str(uuid4()); run_dir.mkdir(parents=True,exist_ok=False)
    (run_dir/'development_snapshot.csv').write_bytes(source.read_bytes())
    base_params = dict(previous['winner_recipe']['params'])
    old_recipe = {**previous['winner_recipe'], 'target_transform':'bps'}
    if previous['winner_recipe']['target_transform'] != 'bps':
        raise ValueError('This controlled study requires a bps baseline recipe')
    search_space = {'objective':['reg:absoluteerror','reg:squarederror'], 'feature_set':list(sets),
                    'train_start':TRAIN_STARTS,'depth':[1,6], 'learning_rate':[.01,.1],
                    'min_child_weight':[20,300], 'lambda':[.1,100], 'alpha':[0,.1,1,10],
                    'subsample':[.6,1.], 'colsample':[.5,1.],
                    'gamma_mae':[0,1,5,20], 'gamma_mse':[0,100,1000,10000]}
    plan = {'created_before_fit_at':datetime.now(timezone.utc),'sampler':'TPESampler(seed=42,n_startup_trials=10)',
            'n_trials':trials,'parallel_trials':1,'optuna_pruner':'NopPruner; XGBoost early stopping only',
            'search_space':search_space,'snapshot_sha256':sha256(source),
            'test_rows_used':0,'selection_metric':'raw MAE Jul-Dec 2025',
            'split_counts':{k:int(v.sum()) for k,v in masks.items()},
            'feature_names':{k:list(v.columns) for k,v in sets.items()},
            'history_control_starts':['2020-01-01','2021-01-01','2022-01-01','2023-01-01','2024-01-01','2024-07-01'],
            'control_recipe':old_recipe,'label_control_seeds':[42,43,44,45,46]}
    write_json(run_dir/'plan.json',plan)
    provenance={'git_commit':git_output('rev-parse','HEAD'),'git_status':git_output('status','--short'),
                'versions':{name:importlib.metadata.version(name) for name in ['optuna','xgboost','pandas','numpy']},
                'code_sha256':{}}
    for file in [Path(__file__),Path('pipeline/decision/hourly_tuning.py'),Path('pipeline/decision/hourly_engineering.py'),
                 Path('pipeline/decision/hourly_features.py'),Path('pipeline/decision/hourly_model.py'),
                 Path('scripts/optimize_hourly.py'),Path('scripts/requirements-hourly.txt')]:
        destination=run_dir/'code'/file.name; destination.parent.mkdir(exist_ok=True); destination.write_bytes(file.read_bytes())
        provenance['code_sha256'][str(file)]=sha256(file)
    write_json(run_dir/'provenance.json',provenance)
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study=optuna.create_study(direction='minimize',sampler=optuna.samplers.TPESampler(seed=42,n_startup_trials=10),
                             pruner=optuna.pruners.NopPruner(),study_name='btc-hourly-validation',
                             storage=f'sqlite:///{(run_dir/"study.sqlite3").resolve()}')
    # Ensure the previous winner is included under the same scoring protocol.
    p=old_recipe['params']
    study.enqueue_trial({'objective':p['objective'],'feature_set':old_recipe['feature_set'],'train_start':old_recipe['train_start'],
                         'max_depth':p['max_depth'],'learning_rate':p['learning_rate'],'min_child_weight':p['min_child_weight'],
                         'reg_lambda':p['reg_lambda'],'reg_alpha':p['reg_alpha'],'gamma_mae':p.get('gamma',0),
                         'subsample':p['subsample'],'colsample_bytree':p['colsample_bytree']})
    results=[]
    def objective(trial):
        recipe=search_recipe(trial,base_params)
        summary,_,_=fit_recipe(recipe,sets,meta,masks,run_dir/recipe['name'])
        summary['number']=trial.number; results.append(summary)
        trial.set_user_attr('recipe',recipe)
        write_json(run_dir/'trial_results.json',results)
        print(f'[{trial.number+1}/{trials}] relative={summary["selection_relative_mae"]:.6f} '
              f'direction={summary["selection_directional_accuracy_pct"]:.2f}% '
              f'{recipe["feature_set"]} start={recipe["train_start"]} depth={recipe["params"]["max_depth"]}',flush=True)
        return summary['selection_mae']
    study.optimize(objective,n_trials=trials,n_jobs=1,gc_after_trial=True)
    best_recipe=study.best_trial.user_attrs['recipe']
    best=next(row for row in results if row['number']==study.best_trial.number)
    history=[]
    for start in plan['history_control_starts']:
        recipe={**old_recipe,'name':f'history_{start}','train_start':start}
        row,_,_=fit_recipe(recipe,sets,meta,masks,run_dir/'controls'/recipe['name']); history.append(row)
        print(f'history {start}: n={row["train_n"]}, relative={row["selection_relative_mae"]:.6f}',flush=True)
    controls=[]
    for seed in plan['label_control_seeds']:
        recipe={**old_recipe,'name':f'labels_shuffled_{seed}'}
        row,_,_=fit_recipe(recipe,sets,meta,masks,run_dir/'controls'/recipe['name'],shuffle_seed=seed); controls.append(row)
        print(f'label control {seed}: relative={row["selection_relative_mae"]:.6f}',flush=True)
    best_dir=run_dir/best_recipe['name']
    (run_dir/'selected_model.ubj').write_bytes((best_dir/'model.ubj').read_bytes())
    write_json(run_dir/'selected_recipe.json',{**best_recipe,'model_sha256':best['model_sha256'],
                                            'best_trees':best['best_trees'],'test_status':'not_evaluated'})
    model=XGBRegressor(); model.load_model(run_dir/'selected_model.ubj')
    val=masks['early_stop']|masks['selection']
    saved=pd.read_csv(best_dir/'validation_predictions.csv',float_precision='round_trip')
    replay=predict_raw(model,sets[best_recipe['feature_set']].loc[val],np.full(int(val.sum()),.0001))
    np.testing.assert_array_equal(replay,saved.predicted_log_return.to_numpy())
    # Last accepted validation sample: remove its target before calling inference.
    input_time=meta.loc[val,'input_open_time'].max()
    context=frame.loc[frame.open_time<=input_time].tail(169)
    infer=predict_candidate(run_dir,context)
    np.testing.assert_allclose(infer,replay[-1],atol=1e-10,rtol=1e-7)
    report={'run_dir':str(run_dir),'created_at':datetime.now(timezone.utc),'plan':plan,
            'snapshot_sha256':sha256(source),'best':best,'best_recipe':best_recipe,'trials':results,
            'history_controls':history,'label_controls':controls,'test_rows_used':0,'test_metrics':None,
            'validation_target_status':'target_met' if best['selection_relative_mae']<=TARGET else 'target_not_met',
            'reload_verified':True,'inference_without_target_verified':True,'live_promotion':False,
            'tree_diagnostics':model_tree_diagnostics(model),'elapsed_seconds':time.monotonic()-started}
    pd.DataFrame(results).sort_values('selection_mae').to_csv(run_dir/'leaderboard.csv',index=False)
    write_json(run_dir/'report.json',report)
    render_optuna(safe_json(report),Path(html_output))
    print(json.dumps(safe_json({'run_dir':str(run_dir),'html':str(html_output),'best':best,
                               'elapsed_seconds':report['elapsed_seconds'],'test_rows_used':0}),ensure_ascii=False,indent=2),flush=True)
    return report
