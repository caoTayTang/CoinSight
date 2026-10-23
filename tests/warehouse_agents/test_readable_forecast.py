import math

from warehouse_agents.tools import readable_forecast


def test_forecast_gets_percent_and_usdt_move():
    result = readable_forecast(dict(predicted_log_return=0.000234, reference_close_usdt=82041.45, predicted_close_usdt=82060.71))
    assert result['expected_move_pct'] == round(math.expm1(0.000234) * 100, 3)
    assert result['expected_move_usdt'] == 19.26


def test_incomplete_forecast_is_left_alone():
    assert readable_forecast({'predicted_log_return': None}) == {'predicted_log_return': None}
    assert 'expected_move_pct' not in readable_forecast(
        dict(predicted_log_return=float('nan'), reference_close_usdt=1.0, predicted_close_usdt=1.0)
    )
