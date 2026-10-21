"""Export the frozen models to standalone Python and prove parity. Never fit."""
from pathlib import Path
import hashlib,importlib.util,json,shutil
import joblib
import numpy as np
import pandas as pd
from pipeline.decision.hourly_engineering import feature_sets
from pipeline.decision.hourly_cross_asset import build_cross_inputs
from pipeline.decision.hourly_future import seal,unseal,digest

SOURCE=Path('data/models/hourly-calibration-research/f9e5fc24-d0d3-442b-9133-f743dc7d5b3d/selected_bundle')
OUTPUT=Path('data/models/agent-serving-bundle/v1')
EVALUATION=Path('data/models/hourly-2026-evaluation/7e5b9fed-17f8-483d-bcd2-356df60024e1')


def prepare():
    if OUTPUT.exists():
        manifest=unseal(OUTPUT/'serving_manifest.json')
        assert all(digest((OUTPUT/e['path']).read_bytes())==e['sha256'] for e in manifest['exports'])
        print('Verified existing serving bundle:',OUTPUT);return
    spec=unseal(SOURCE/'ensemble.json');OUTPUT.mkdir(parents=True,exist_ok=False)
    shutil.copy2(SOURCE/'ensemble.json',OUTPUT/'ensemble.json')
    raw={a:pd.read_csv(EVALUATION/f'{a}_snapshot.csv',float_precision='round_trip') for a in ('btc','eth')}
    for d in raw.values():d.open_time=pd.to_datetime(d.open_time,utc=True)
    sets,meta,_=feature_sets(raw['btc'])
    saved=pd.read_csv(EVALUATION/'predictions.csv',float_precision='round_trip');cutoffs=pd.to_datetime(saved.input_open_time,utc=True)
    inputs=dict(compact=sets['compact'].reindex(cutoffs))
    inputs['eth']=pd.concat([inputs['compact'],build_cross_inputs(raw['btc'],raw['eth']).reindex(cutoffs)],axis=1)
    total=np.zeros(len(saved));entries=[]
    for member in spec['members']:
        src=SOURCE/member['path'];assert digest(src.read_bytes())==member['model_sha256']
        model=joblib.load(src);assert not model.get_cat_feature_indices()
        shutil.copy2(src,OUTPUT/member['path'])
        export=OUTPUT/Path(member['path']).with_suffix('.py');model.save_model(str(export),format='python')
        module_spec=importlib.util.spec_from_file_location('export_'+export.stem,export);module=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(module)
        # Restore the native float32 border representation before comparisons.
        module.catboost_model.float_feature_borders=[[float(np.float32(b)) for b in row] for row in module.catboost_model.float_feature_borders]
        native_borders=model.get_borders()
        for index,borders in zip(module.catboost_model.float_features_index,module.catboost_model.float_feature_borders):
            np.testing.assert_array_equal(borders,native_borders[index])
        x=inputs[member['feature_set']];assert list(x.columns)==member['features'] and not x.isna().any().any()
        # Native CatBoost quantizes numeric inputs as float32 before its border comparisons.
        portable=np.array([module.apply_catboost_model(row) for row in x.to_numpy(dtype=np.float32).tolist()])
        native=model.predict(x,thread_count=2)
        max_delta=float(np.max(np.abs(portable-native)))
        np.testing.assert_allclose(portable,native,rtol=0,atol=1e-10)
        total+=member['coefficient']*portable/member['target_divisor']
        entries.append(dict(path=export.name,sha256=digest(export.read_bytes()),source_model_sha256=member['model_sha256'],native_max_abs_delta_bps=max_delta))
        print(export.name,'verified',len(saved),'native predictions; max delta bps',max_delta,flush=True)
    delta=float(np.max(np.abs(total-saved.predicted_log_return.to_numpy())))
    np.testing.assert_allclose(total,saved.predicted_log_return.to_numpy(),rtol=0,atol=1e-12)
    seal(OUTPUT/'serving_manifest.json',dict(format='catboost-python-export-v1',source_spec_payload_sha256=unseal_source_hash(),
        float32_features_and_borders=True,exports=entries,verified_test_rows=len(saved),ensemble_max_abs_delta_log_return=delta,no_training=True))
    print('Portable bundle ready:',OUTPUT,'ensemble max error',delta,flush=True)
    print(entries,flush=True)


def unseal_source_hash():return json.loads((SOURCE/'ensemble.json').read_text())['sha256']

if __name__=='__main__':prepare()
