import math

import pytest

from scripts.export_eda_html import SafeTable, derived_series, saved_cell, saved_plot


def test_returns_from_normalized_prices_and_drawdown():
    returns, drawdowns = derived_series({
        'x': ['2024-01-01T00:00:00+00:00', '2024-01-02T00:00:00+00:00',
              '2024-01-03T00:00:00+00:00'],
        'y': [100, 120, 90],
    })
    assert returns == pytest.approx([math.log(1.2) * 100, math.log(.75) * 100])
    assert drawdowns == pytest.approx([0, 0, -25])


def test_return_does_not_bridge_missing_days():
    returns, _ = derived_series({
        'x': ['2024-01-01T00:00:00+00:00', '2024-01-03T00:00:00+00:00'],
        'y': [100, 120],
    })
    assert returns == []


def test_notebook_table_strips_executable_content():
    parser = SafeTable()
    parser.feed('<style>hidden</style><script>alert(1)</script>'
                '<table onclick="bad()"><tr><td>BTC &amp; ETH</td></tr></table>'
                '<img src="https://example.com/tracker">')
    result = ''.join(parser.parts)
    assert '<table>' in result
    assert 'BTC &amp; ETH' in result
    for removed in ('script', 'alert', 'onclick', 'hidden', '<img', 'tracker'):
        assert removed not in result


def test_missing_saved_output_is_explicit():
    notebook = {'cells': [{'cell_type': 'code', 'source': ['example = 1'], 'outputs': []}]}
    with pytest.raises(ValueError, match='No saved Plotly'):
        saved_plot(notebook, 'example =')
    with pytest.raises(ValueError, match='Expected one'):
        saved_cell(notebook, 'not present')
