import test from 'node:test';
import assert from 'node:assert/strict';
import { coinHistory, dataHealth, expectedLatestDay } from './dataHealth.js';

const NOW = Date.parse('2026-10-25T10:00:00Z');
const day = (symbol, first, last = '2026-10-24T00:00:00Z') => ({ symbol, candle_interval: '1d', first_open: first, last_open: last });
const COVERAGE = [
  day('BTC', '2024-01-01T00:00:00Z'), day('ETH', '2024-01-01T00:00:00Z'), day('ATOM', '2026-10-21T00:00:00Z'),
  { symbol: 'BTC', candle_interval: '1h', first_open: '2020-01-01T00:00:00Z', missing_candles: 31 },
  { symbol: 'ATOM', candle_interval: '1h', first_open: '2026-10-21T00:00:00Z', missing_candles: 0 },
];
const healthy = {
  warehouse: { data: { latest_batch_id: 12, latest_batch_status: 'success', latest_batch_finished_at: '2026-10-25T06:30:00Z', rejected_rows: 0 } },
  evaluation: { data: { decision: 'rejected' }, provenance: { computed_at: '2026-10-19T07:40:00Z' } },
  prediction: { status: 'insufficient_data' },
  live: { summary: { data: { observed_minutes: 15, expected_minutes: 15 } } },
  coverage: COVERAGE, now: NOW,
};

test('the expected newest day is yesterday once the 06:00 UTC load has had time to finish', () => {
  assert.equal(expectedLatestDay(Date.parse('2026-10-25T10:00:00Z')), Date.parse('2026-10-24T00:00:00Z'));
  assert.equal(expectedLatestDay(Date.parse('2026-10-25T05:00:00Z')), Date.parse('2026-10-23T00:00:00Z'));
});

test('coins split into full history and recent only; missing hours are listed', () => {
  const h = coinHistory(COVERAGE, NOW);
  assert.deepEqual(h.full.symbols, ['BTC', 'ETH']);
  assert.deepEqual(h.recent.symbols, ['ATOM']);
  assert.deepEqual(h.missingHours.map((m) => [m.symbol, m.count]), [['BTC', 31]]);
  assert.equal(h.late, false);
  assert.equal(coinHistory([], NOW), null);
});

test('a healthy warehouse reads as current; a rejected model is a note, not a problem', () => {
  const r = dataHealth(healthy);
  assert.equal(r.verdict.tone, 'ok');
  assert.match(r.verdict.text, /Data is current\. Newest day: 24 Oct/);
  assert.equal(r.rows.find((x) => x.key === 'model').tone, 'note');
  assert.match(r.rows.find((x) => x.key === 'model').text, /no better than guessing/);
});

test('a stale newest day, a failed load or a silent live feed needs attention', () => {
  const stale = dataHealth({ ...healthy, coverage: [day('BTC', '2024-01-01T00:00:00Z', '2026-10-20T00:00:00Z')] });
  assert.equal(stale.verdict.tone, 'problem');
  assert.match(stale.rows[0].text, /newest day is 20 Oct, expected 24 Oct/);
  const failed = dataHealth({ ...healthy, warehouse: { data: { ...healthy.warehouse.data, latest_batch_status: 'failed' } } });
  assert.match(failed.verdict.text, /daily load/);
  const silent = dataHealth({ ...healthy, live: { summary: { quality: { warnings: ['No closed candles'] } } } });
  assert.match(silent.verdict.text, /live prices/);
  const opening = dataHealth({ ...healthy, live: { connection: 'connecting', summary: null } });
  assert.equal(opening.verdict.tone, 'ok');
  assert.match(opening.rows.find((x) => x.key === 'live').text, /Connecting/);
});

test('before the requests answer, the tab says it is checking instead of raising an alarm', () => {
  const r = dataHealth({ live: { connection: 'connecting' }, now: NOW });
  assert.equal(r.verdict.tone, 'loading');
  assert.equal(r.rows.filter((x) => x.tone === 'problem').length, 0);
});
