import test from 'node:test';
import assert from 'node:assert/strict';
import {parseDeskInput,toolHelp} from './deskCommands.js';
test('plain text asks the Analyst agent about the selected asset',()=>assert.deepEqual(parseDeskInput('market brief','ETH'),{kind:'command',command:'trade',question:'market brief',symbol:'ETH'}));
test('plain text without a supported asset defaults to BTC',()=>assert.equal(parseDeskInput('hello','DOGE').symbol,'BTC'));
test('public Trade/SRE names select roles explicitly',()=>{
  assert.deepEqual(parseDeskInput('@trade inspect BTC','BTC'),{kind:'command',command:'trade',question:'inspect BTC',symbol:'BTC'});
  assert.equal(parseDeskInput('@sre inspect coverage','ETH').symbol,'ETH');
  assert.equal(parseDeskInput('/sre inspect','BTC').command,'sre');
  assert.throws(()=>parseDeskInput('@sre inspect','DOGE'),/Select BTC/);
});
test('direct tools require BTC and reject accidental extra arguments',()=>{
  for (const c of ['/predict','/anomaly','/drift']) {
    assert.equal(parseDeskInput(c+' BTC','ETH').symbol,'BTC');
    assert.throws(()=>parseDeskInput(c,'ETH'),/BTC only/);
    assert.throws(()=>parseDeskInput(c+' BTC nonsense'),/Use/);
  }
});
test('command errors do not silently fall into legacy LLM',()=>{
  for (const c of ['@ops hi','/unknown','@trade','@sre','/tools extra']) assert.throws(()=>parseDeskInput(c));
  assert.equal(parseDeskInput('/tools').kind,'tools');
  assert.match(toolHelp(),/Contracts/);
});
