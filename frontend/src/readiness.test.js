import test from 'node:test';
import assert from 'node:assert/strict';
import {liveReadiness, predictionReadiness} from './readiness.js';
const now = Date.parse('2026-10-07T10:00:00Z');
const healthy = () => ({connection: 'connected', now, summary: {status: 'ready', provenance: {observed_at: '2026-10-07T09:59:00Z'}, data: {observed_minutes: 15, expected_minutes: 15}}});
test('socket open without observations is unavailable', () => assert.equal(liveReadiness({connection: 'connected', now}).status, 'unavailable'));
test('fresh complete observations are ready', () => assert.equal(liveReadiness(healthy()).status, 'ready'));
test('age advances even with no new payload', () => assert.equal(liveReadiness({...healthy(), now: now + 181000}).status, 'stale'));
test('fresh incomplete window does not become a full-window claim', () => {
 const live = healthy(); live.summary.data.observed_minutes = 8;
 assert.equal(liveReadiness(live).status, 'insufficient_data');
});
test('retained observations are labelled disconnected', () => assert.equal(liveReadiness({...healthy(), connection: 'reconnecting'}).status, 'disconnected'));
test('missing timestamp is unverified', () => {
 const live = healthy(); live.summary.provenance = {};
 assert.equal(liveReadiness(live).status, 'stale');
});
test('model probability requires current date, ready status and valid range', () => {
 const prediction = {status: 'ready', data: {target_date: '2026-10-07', probability_up: .6}};
 assert.equal(predictionReadiness(prediction, now), true);
 assert.equal(predictionReadiness({...prediction, status: 'stale'}, now), false);
 assert.equal(predictionReadiness(prediction, now + 86400000), false);
 assert.equal(predictionReadiness({...prediction, data: {...prediction.data, probability_up: 2}}, now), false);
 assert.equal(predictionReadiness(null, now), false);
});
