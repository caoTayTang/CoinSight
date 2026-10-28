import assert from 'node:assert/strict';
import test from 'node:test';

import { decisionTone, equityDomain, equityPath } from './trading/tradingApi.js';

test('decision tones distinguish buy and risk exits', () => {
  assert.equal(decisionTone('BUY'), 'positive');
  assert.equal(decisionTone('SELL'), 'negative');
  assert.equal(decisionTone('HOLD'), '');
});

test('equity path is empty without a line and finite otherwise', () => {
  assert.equal(equityPath([]), '');
  assert.equal(equityPath([{ equity_usdt: 100 }]), '');
  const path = equityPath([{ equity_usdt: 100 }, { equity_usdt: 110 }, { equity_usdt: 105 }]);
  assert.match(path, /^M/);
  assert.doesNotMatch(path, /NaN|Infinity/);
});

test('comparison curves can share one equity domain', () => {
  const domain = equityDomain([100, 110], [100, 80]);
  assert.deepEqual(domain, { low: 80, high: 110 });
  const policy = equityPath([{ equity_usdt: 100 }, { equity_usdt: 110 }], 100, 100, 10, domain);
  const benchmark = equityPath([{ equity_usdt: 100 }, { equity_usdt: 80 }], 100, 100, 10, domain);
  assert.notEqual(policy, benchmark);
  assert.doesNotMatch(`${policy}${benchmark}`, /NaN|Infinity/);
});
