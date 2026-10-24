import test from 'node:test';
import assert from 'node:assert/strict';
import {stepSummary,answerTime} from './answerViews.js';

test('steps read as verbs in order; repeats collapse; skills name their guide',()=>{
  const s=stepSummary({steps:[
    {latency_ms:1000,tools:[{name:'predict_hourly',status:'success',latency_ms:200},{name:'model_health',status:'success'}]},
    {latency_ms:500,tools:[{name:'load_skill',arguments:{name:'forecast-explainer'},status:'success'}]},
    {latency_ms:300,tools:[{name:'warehouse_coverage',status:'error'},{name:'warehouse_coverage',status:'success'}]},
    {latency_ms:800}]});
  assert.deepEqual(s.items.map(i=>i.label),['Checked the forecast','Checked model accuracy','Read the forecast explainer guide','Counted hourly candles']);
  assert.equal(s.items[3].count,2); assert.equal(s.seconds,2.8);
  assert.equal(stepSummary({steps:[{latency_ms:5}]}),null);
});

test('direct commands carry evidence as an object; reading the answer time must not crash',()=>{
  assert.equal(answerTime({evidence:{trained:{score:.4}},created_at:'2026-10-24T06:00:00Z'}),Date.parse('2026-10-24T06:00:00Z'));
  assert.equal(typeof answerTime({evidence:{trained:{}}}),'number');
  assert.equal(answerTime({evidence:[{result:{observed_at:'2026-10-24T05:00:00Z'}}]}),Date.parse('2026-10-24T05:00:00Z'));
});
