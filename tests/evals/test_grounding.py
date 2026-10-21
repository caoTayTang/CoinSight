from warehouse_agents.grounding import check_grounding, extract_numbers

EVIDENCE = [
    {
        'tool': 'warehouse_coverage',
        'arguments': {'symbol': 'BTC', 'hours': 48},
        'result': {
            'status': 'available',
            'observed_at': '2026-10-21T05:00:00+00:00',
            'rows': [
                {
                    'expected_hours': 48,
                    'observed_hours': 45,
                    'missing_hours': 3,
                    'last_observed_open': '2026-10-21T04:00:00+00:00',
                }
            ],
        },
    }
]


def values(text):
    return [sorted(v for v, _ in n['values']) for n in extract_numbers(text)]


def test_numbers_from_evidence_are_grounded():
    report = check_grounding('BTC is missing 3 of 48 hours (45 observed).', EVIDENCE)
    assert report == {'total': 3, 'grounded': 3, 'ungrounded': []}


def test_invented_number_is_flagged():
    report = check_grounding('BTC is missing 5 hours.', EVIDENCE)
    assert report['ungrounded'] == ['5']


def test_simple_derivations_are_grounded():
    # 3 / 48 = 6.25% and 48 - 45 = 3 are derivations from one tool result.
    assert check_grounding('Coverage gap is 6.25% of the window.', EVIDENCE)['ungrounded'] == []
    # 45 / 48 = 93.75% is derivable; 97% is not.
    assert check_grounding('Coverage is 97%.', EVIDENCE)['ungrounded'] == ['97%']


def test_dates_times_hashes_identifiers_and_list_markers_are_not_claims():
    text = (
        '1. Last candle at 2026-10-21T04:00:00Z (04:00 UTC).\n'
        '2. Checked `fact_ohlcv_hourly` via mv_hourly_activity, sha256 9466aeeeac0b (SHA-256).'
    )
    assert extract_numbers(text) == []


def test_unicode_dashes_in_dates():
    assert extract_numbers('observed at 2026\u201110\u201121 06:41 UTC') == []


def test_vietnamese_and_english_separators():
    assert [1234.5] in values('1,234.5')
    assert [1234.5] in values('1.234,5')
    # Ambiguous between 0.997 and 997; either interpretation may ground it.
    assert 0.997 in values('0,997')[0]


def test_percent_matches_fraction_in_evidence():
    evidence = [{'tool': 't', 'arguments': {}, 'result': {'alert_rate': 0.011168}}]
    assert check_grounding('Alert rate is 1.12%.', evidence)['ungrounded'] == []


def test_timestamp_hours_do_not_ground_bare_numbers():
    # observed_at is 05:00; a bare "5" must not be grounded by the hour of a timestamp.
    assert check_grounding('5 hours are missing.', EVIDENCE)['ungrounded'] == ['5']
    assert check_grounding('Checked on 21 October 2026.', EVIDENCE)['ungrounded'] == []


def test_question_numbers_are_context():
    report = check_grounding('Checked the last 72 hours.', [], context=['Check SOL for 72 hours'])
    assert report['ungrounded'] == []


def test_rounding_respects_shown_precision():
    evidence = [{'tool': 't', 'arguments': {}, 'result': {'relative_mae': 0.9970170386}}]
    assert check_grounding('Relative MAE 0.997.', evidence)['ungrounded'] == []
    assert check_grounding('Relative MAE 0.95.', evidence)['ungrounded'] == ['0.95']


def test_thin_space_thousands_separator():
    # Seen in a real gpt-oss-120b answer: 200 027 899.76
    evidence = [{'tool': 't', 'arguments': {}, 'result': {'fact_volume': 200027899.76}}]
    assert check_grounding('Volume 200 027 899.76 USDT.', evidence)['ungrounded'] == []


def test_number_words_in_tool_contract_ground_digits():
    report = check_grounding(
        'Covers the last 7 days.', [], context=['Read last seven days of ETL batch states.']
    )
    assert report['ungrounded'] == []
