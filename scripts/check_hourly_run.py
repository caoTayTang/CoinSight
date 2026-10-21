"""Independently replay a frozen hourly run and verify its linked source ZIPs.

Does not fit, tune, promote or change the saved model/report.json.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from pipeline.decision.hourly_features import build_dataset, prepare_grid
from pipeline.decision.hourly_model import render_report, sha256, write_json
from scripts.verify_eda import inspect_archives


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--raw-dir', type=Path, default=Path('data/raw'))
    parser.add_argument('--html', type=Path, help='Optionally render HTML with the additional source audit')
    args = parser.parse_args()
    run = args.run_dir
    report = json.loads((run / 'report.json').read_text())
    frame = pd.read_csv(run / 'snapshot.csv', float_precision='round_trip')
    frame['open_time'] = pd.to_datetime(frame.open_time, utc=True)
    if sha256(run / 'snapshot.csv') != report['snapshot_sha256']:
        raise ValueError('Snapshot checksum mismatch')
    if sha256(run / 'model.ubj') != report['model_sha256']:
        raise ValueError('Model checksum mismatch')
    archives = inspect_archives(frame, args.raw_dir, interval='1h')
    features, meta, _ = build_dataset(frame)
    saved = pd.read_csv(run / 'predictions.csv', float_precision='round_trip')
    saved['target_open_time'] = pd.to_datetime(saved.target_open_time, utc=True)
    if not saved.target_open_time.equals(meta.target_open_time.reset_index(drop=True)):
        raise ValueError('Saved predictions do not match target timestamps')
    model = XGBRegressor()
    model.load_model(run / 'model.ubj')
    if model.get_booster().feature_names != json.loads((run / 'feature_names.json').read_text()):
        raise ValueError('Feature schema mismatch')
    replay = model.predict(features, iteration_range=(0, report['best_iteration'] + 1))
    np.testing.assert_array_equal(replay, saved.predicted_log_return.to_numpy())
    np.testing.assert_allclose(saved.actual_log_return, meta.actual_log_return, rtol=0, atol=0)
    if not np.isfinite(replay).all():
        raise ValueError('Non-finite replay predictions')
    grid, _, _ = prepare_grid(frame)
    missing = grid.index.difference(frame.open_time)
    evidence = {'checked_at':datetime.now(timezone.utc), 'snapshot_hash_verified':True,
                'model_hash_verified':True, 'reload_predictions_exact':True,
                'prediction_rows_verified':len(replay), 'local_archives_verified':len(archives),
                'facts_compared_to_zip':sum(a['linked_facts'] for a in archives),
                'facts_without_lineage':len(frame) - sum(a['linked_facts'] for a in archives),
                'missing_hours':[t.isoformat() for t in missing], 'archives':archives}
    write_json(run / 'source_and_replay_checks.json', evidence)
    summary = {k:v for k,v in evidence.items() if k not in ['archives', 'missing_hours']}
    if args.html:
        report['independent_checks'] = summary
        render_report(report, saved, args.html)
    print(json.dumps({k:str(v) if isinstance(v, datetime) else v for k,v in summary.items()}, indent=2))


if __name__ == '__main__':
    main()
