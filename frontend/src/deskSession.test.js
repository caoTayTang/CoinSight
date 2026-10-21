import test from 'node:test';
import assert from 'node:assert/strict';
import {modelOptionLabel,promptOf,runsToMessages} from './deskSession.js';

test('stored runs read back as the user typed them',()=>{
  assert.equal(promptOf({command:'sre',question:'check BTC'}),'@sre check BTC');
  assert.equal(promptOf({command:'predict',question:'',symbol:'BTC'}),'/predict BTC');
  assert.equal(promptOf({command:'trade',question:'price now?'}),'price now?');
});

test('runs become user and agent messages, failures stay visible',()=>{
  const messages=runsToMessages([
    {command:'trade',question:'q',status:'ok',answer:'a',steps:[{step:1}],evidence:[]},
    {command:'sre',question:'q2',status:'error',error:'down'},
  ]);
  assert.deepEqual(messages.map(m=>m.role),['user','agent','user','agent error']);
  assert.deepEqual(messages[1].commandMeta.steps,[{step:1}]);
  assert.equal(messages[3].text,'down');
});

test('picker labels show eval results and missing keys',()=>{
  assert.equal(modelOptionLabel({label:'GPT-OSS 120B · Groq',available:true,eval:{pass_rate:0.964,latency_p50_ms:2967}}),'GPT-OSS 120B · Groq · 96% eval · 3.0 s');
  assert.equal(modelOptionLabel({label:'Gemma',available:false}),'Gemma · no key');
});
