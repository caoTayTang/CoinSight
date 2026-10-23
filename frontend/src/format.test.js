import test from 'node:test';
import assert from 'node:assert/strict';
import {unified} from 'unified';
import remarkParse from 'remark-parse';
import {when,readableTimes} from './format.js';

const now=Date.parse('2026-10-23T10:26:00Z');
test('timestamps read as time plus today, yesterday or a short date',()=>{
  assert.equal(when('2026-10-23T10:00:00+00:00',now),'10:00 UTC today');
  assert.equal(when('2026-10-23T08:46:34.123+07:00',now),'01:46 UTC today');
  assert.equal(when('2026-10-22T23:59:00Z',now),'23:59 UTC yesterday');
  assert.equal(when('2026-10-18T05:00:00Z',now),'18 Oct, 05:00 UTC');
  assert.equal(when('2025-12-31T05:00:00Z',now),'31 Dec 2025, 05:00 UTC');
  assert.equal(when('not a date',now),'not a date');
});
test('answers: ISO stamps in text are rewritten, code is not',()=>{
  const tree=unified().use(remarkParse).parse('Observed 2026-10-23T10:00:00+00:00.\n\n`2026-10-23T10:00:00Z`');
  readableTimes()(tree);
  assert.match(tree.children[0].children[0].value,/^Observed \d\d:\d\d UTC|^Observed \d+ \w+/);
  assert.doesNotMatch(tree.children[0].children[0].value,/T10:00/);
  assert.equal(tree.children[1].children[0].value,'2026-10-23T10:00:00Z');
});
