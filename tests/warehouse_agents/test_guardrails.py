import pytest
from warehouse_agents.guardrails import guard_answer, reject_credentials
from warehouse_agents.graph import Reasoner


def test_all_unavailable_replaces_false_healthy_claim():
    answer, meta = guard_answer(
        'Everything is healthy. BTC will rise 95%.',
        [{'tool': 'warehouse_status', 'result': {'status': 'unavailable'}}],
    )
    assert 'healthy' not in answer and '95%' not in answer
    assert 'could not be verified' in answer
    assert meta['evidence_status'] == 'unavailable'


def test_delegation_wrapper_cannot_hide_missing_evidence():
    trace = [
        {'result': {'status': 'available', 'result': {'evidence': [{'result': {'status': 'unavailable'}}]}}}
    ]
    _, meta = guard_answer('All good', trace)
    assert meta['evidence_status'] == 'unavailable'


def test_partial_and_no_evidence_are_explicit_without_claiming_proof():
    answer, meta = guard_answer(
        'Some data returned', [{'result': {'status': 'available'}}, {'result': {'status': 'unavailable'}}]
    )
    assert answer == 'Some data returned' and meta['evidence_status'] == 'partial' and meta['warnings']
    _, meta = guard_answer('An explanation', [])
    assert meta['evidence_status'] == 'none' and 'not a verified' in meta['warnings'][0]


def test_secret_input_rejected_output_redacted(monkeypatch):
    secret = 'a-private-configured-secret-that-is-not-a-known-provider-prefix'
    monkeypatch.setenv('GROQ_API_KEY', secret)
    with pytest.raises(ValueError):
        reject_credentials('Please use ' + secret)
    with pytest.raises(ValueError):
        reject_credentials('gsk_' + 'x' * 25)
    answer, meta = guard_answer('Here is ' + secret, [])
    assert secret not in answer and '[credential redacted]' in answer


def test_every_key_in_a_list_value_is_guarded(monkeypatch):
    first, second = 'first-private-key-not-a-known-prefix', 'second-private-key-not-a-known-prefix'
    monkeypatch.setenv('GROQ_API_KEY', f'["{first}", "{second}"]')
    for secret in (first, second):
        with pytest.raises(ValueError):
            reject_credentials('Please use ' + secret)
        assert secret not in guard_answer('Here is ' + secret, [])[0]


@pytest.mark.asyncio
async def test_credential_input_never_reaches_provider():
    class Backend:
        async def converse(self, **kwargs):
            pytest.fail('Secret sent to provider')

    with pytest.raises(ValueError):
        await Reasoner('analyst', Backend()).run('gsk_' + 'x' * 25)


@pytest.mark.asyncio
async def test_invalid_arguments_are_not_executed_and_can_be_repaired():
    from tests.warehouse_agents.test_intelligence import FakeBackend, use

    calls = []

    async def health(**kwargs):
        calls.append(kwargs)
        return {'status': 'available', 'observed_at': 'now'}

    backend = FakeBackend(
        [use('model_health', {'symbol': 'BTC'}), use('model_health'), [{'text': 'Observation returned.'}]]
    )
    result = await Reasoner('analyst', backend, {'model_health': health}).run('Inspect BTC')
    assert calls == [{}]
    error = result['evidence'][0]['result']
    assert error['retryable'] and error['allowed_keys'] == ['cutoff']
    assert result['evidence'][1]['result']['status'] == 'available'
    assert result['llm_calls'] == 3
