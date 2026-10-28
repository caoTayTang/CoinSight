"""Forecast entry points.

The daily support service is public.  The frozen hourly ensemble remains here
for one release as an explicit rollback path and is not advertised by MCP.
"""

from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib, json, os, types
from pathlib import Path
import numpy as np
import pandas as pd
from agents.domain import CandleContext
from pipeline.decision.hourly_engineering import build_experimental_inputs
from pipeline.decision.hourly_cross_asset import build_cross_inputs

BUNDLE = Path(os.getenv('HOURLY_ENSEMBLE_BUNDLE', 'data/models/agent-serving-bundle/v1'))
EXPECTED_SPEC = 'ab8716aeb805ac18f4f5be3da9cf6357aaaf3c907d81a5d707428099b5783725'
EXPECTED_EXPORTS = {
    'member_0.py': 'd00be2b20c8cb1157621f9bef98b454491ffe018f9ad360fef3abb0dde443ada',
    'member_2.py': '5ec66cdec9ea2d34aaa4c9f26b182e485d32721eb948bac7560de379ff37c6c2',
}


def forecast_support(
    symbol: str = 'BTC',
    performance_days: int = 30,
    market_days: int = 30,
    trend_hours: int = 168,
    cutoff: str | None = None,
) -> dict:
    """Run bounded daily support inference, including readiness/backfill."""
    from pipeline.decision.serving.support_service import forecast_support as run

    return run(
        symbol=symbol,
        performance_days=performance_days,
        market_days=market_days,
        trend_hours=trend_hours,
        cutoff=cutoff,
    )


@lru_cache(maxsize=1)
def frozen_models():
    record = json.loads((BUNDLE / 'ensemble.json').read_text())
    spec = record['payload']
    raw = json.dumps(spec, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if hashlib.sha256(raw).hexdigest() != record['sha256'] or record['sha256'] != EXPECTED_SPEC:
        raise ValueError('Serving bundle differs from approved frozen research ensemble')
    manifest_record = json.loads((BUNDLE / 'serving_manifest.json').read_text())
    manifest = manifest_record['payload']
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if (
        hashlib.sha256(manifest_bytes).hexdigest() != manifest_record['sha256']
        or manifest['source_spec_payload_sha256'] != EXPECTED_SPEC
        or not manifest['float32_features_and_borders']
    ):
        raise ValueError('Invalid portable serving manifest')
    models = []
    for member in spec['members']:
        path = BUNDLE / member['path']
        if hashlib.sha256(path.read_bytes()).hexdigest() != member['model_sha256']:
            raise ValueError('Frozen model hash mismatch')
        export_path = BUNDLE / Path(member['path']).with_suffix('.py')
        code = export_path.read_bytes()
        if hashlib.sha256(code).hexdigest() != EXPECTED_EXPORTS[export_path.name]:
            raise ValueError('Portable model hash mismatch')
        # Execute exactly the bytes checked above, without reading an unverified __pycache__.
        module = types.ModuleType('coinsight_' + export_path.stem)
        exec(compile(code, str(export_path), 'exec'), module.__dict__)
        module.catboost_model.float_feature_borders = [
            [float(np.float32(b)) for b in row] for row in module.catboost_model.float_feature_borders
        ]
        models.append((member, module.apply_catboost_model))
    return spec, models


def predict(btc: CandleContext, eth: CandleContext) -> dict:
    """Legacy BTC hourly rollback implementation."""
    if btc.cutoff != eth.cutoff:
        raise ValueError('BTC/ETH cutoff mismatch')

    def frame(ctx):
        return pd.DataFrame([c.model_dump() for c in ctx.candles])

    b, e = frame(btc), frame(eth)
    compact = build_experimental_inputs(b)['compact'].iloc[[-1]]
    sets = dict(compact=compact, eth=pd.concat([compact, build_cross_inputs(b, e).iloc[[-1]]], axis=1))
    spec, models = frozen_models()
    total = 0.0
    for member, model in models:
        x = sets[member['feature_set']]
        if list(x.columns) != member['features'] or x.isna().any().any():
            raise ValueError('Incomplete feature schema')
        total += (
            member['coefficient']
            * float(model(x.to_numpy(dtype=np.float32)[0].tolist()))
            / member['target_divisor']
        )
    if not np.isfinite(total):
        raise ValueError('Non-finite forecast')
    now = datetime.now(timezone.utc)
    reference = btc.candles[-1].close_price
    return dict(
        agent='prediction',
        model_id='btc_hourly_frozen_ensemble_v1',
        inference_backend='verified_catboost_python_export',
        bundle_payload_sha256=EXPECTED_SPEC,
        cutoff=btc.cutoff.isoformat(),
        target_open=btc.cutoff.isoformat(),
        target_close=(btc.cutoff + timedelta(hours=1)).isoformat(),
        generated_at=now.isoformat(),
        target_already_started=now > btc.cutoff,
        timing='historical' if now >= btc.cutoff + timedelta(hours=1) else 'target_hour_in_progress',
        predicted_log_return=total,
        reference_close_usdt=reference,
        predicted_close_usdt=float(reference * np.exp(total)),
        direction='up' if total > 0 else ('down' if total < 0 else 'flat'),
        research_test=dict(
            relative_mae=0.9970170386973569,
            directional_accuracy_pct=52.9639175257732,
            sample_hours=6984,
            period='2026-01-01 through 2026-10-18 UTC',
            status='retrospective',
        ),
        interpretation='Research model output, not a probability, confidence interval, or trading instruction.',
    )
