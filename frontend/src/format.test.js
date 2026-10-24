process.env.TZ='Asia/Ho_Chi_Minh';  // UTC+7, the owner's timezone
import test from 'node:test';
import assert from 'node:assert/strict';
import {unified} from 'unified';
import remarkParse from 'remark-parse';
import {when,localTimes,readableTimes,utc} from './format.js';

const now=Date.parse('2026-10-23T10:26:00Z');  // 17:26 on 23 Oct in UTC+7
test('timestamps show in the viewer timezone with today, yesterday or a short date',()=>{
  assert.equal(when('2026-10-23T10:00:00+00:00',now),'17:00 today');
  assert.equal(when('2026-10-22T18:30:00Z',now),'01:30 today');  // still 22 Oct in UTC, already 23 Oct here
  assert.equal(when('2026-10-22T08:46:34Z',now),'15:46 yesterday');
  assert.equal(when('2026-10-18T05:00:00Z',now),'18 Oct, 12:00');
  assert.equal(when('2025-12-31T05:00:00Z',now),'31 Dec 2025, 12:00');
  assert.equal(when('not a date',now),'not a date');
});
test('times written in answers: ISO, dated UTC and bare UTC; zone-less dates stay',()=>{
  const ref=Date.parse('2026-10-22T08:46:36Z'), today=Date.now();
  assert.equal(localTimes('observed 08:46 UTC',ref),`observed ${when('2026-10-22T08:46:00Z',today)}`);
  assert.equal(localTimes('at 23:50 UTC',Date.parse('2026-10-23T00:10:00Z')),`at ${when('2026-10-22T23:50:00Z',today)}`);  // nearest day
  assert.equal(localTimes('2026‑10‑22 08:46 UTC',ref),when('2026-10-22T08:46:00Z',today));
  assert.equal(localTimes('2026-10-22T08:46:34.79+00:00',ref),when('2026-10-22T08:46:00Z',today));
  assert.equal(localTimes('date 2026-10-22 08:46 only',ref),'date 2026-10-22 08:46 only');
  assert.equal(localTimes('score 99:99 UTC',ref),'score 99:99 UTC');
});
test('answers: code is left alone; day-only dates are not shifted',()=>{
  const tree=unified().use(remarkParse).parse('Seen 10:00 UTC.\n\n`10:00 UTC`');
  readableTimes(now)()(tree);
  assert.doesNotMatch(tree.children[0].children[0].value,/UTC/);
  assert.equal(tree.children[1].children[0].value,'10:00 UTC');
  assert.equal(utc('2026-10-23'),'23 Oct 2026');
  assert.equal(utc('2026-10-23T10:00:00Z',true),'23 Oct 2026, 17:00');
});
