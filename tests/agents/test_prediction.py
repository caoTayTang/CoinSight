from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from agents.domain import CandleContext
from agents.prediction import predict, BUNDLE


@pytest.mark.skipif(not BUNDLE.exists(), reason='Local research bundle is a read-only deployment artifact')
def test_serving_prediction_matches_saved_2026_forecast_without_label():
    root = Path('data/models/hourly-2026-evaluation/7e5b9fed-17f8-483d-bcd2-356df60024e1')
    if not root.exists():
        pytest.skip('Optional local evaluation snapshot')
    expected = pd.read_csv(root / 'predictions.csv', float_precision='round_trip').iloc[100]
    cutoff = pd.Timestamp(expected.cutoff_time)
    contexts = {}
    for asset in ('btc', 'eth'):
        frame = pd.read_csv(root / f'{asset}_snapshot.csv', float_precision='round_trip')
        frame.open_time = pd.to_datetime(frame.open_time, utc=True)
        frame = frame[frame.open_time.ge(cutoff - pd.Timedelta(hours=169)) & frame.open_time.lt(cutoff)]
        contexts[asset] = CandleContext(cutoff=cutoff, candles=frame.to_dict('records'))
    got = predict(contexts['btc'], contexts['eth'])
    np.testing.assert_allclose(
        got['predicted_log_return'], expected.predicted_log_return, rtol=1e-8, atol=1e-12
    )
