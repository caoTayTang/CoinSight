import test from 'node:test';
import assert from 'node:assert/strict';
import {parseDeskInput,toolHelp} from './deskCommands.js';
test('plain text asks the Analyst agent about the selected asset',()=>assert.deepEqual(parseDeskInput('market brief','ETH'),{kind:'command',command:'trade',question:'market brief',symbol:'ETH'}));
test('plain text without a supported asset defaults to BTC',()=>assert.equal(parseDeskInput('hello','DOGE').symbol,'BTC'));
test('public Trade/SRE names select roles explicitly',()=>{
  assert.deepEqual(parseDeskInput('@trade inspect BTC','BTC'),{kind:'command',command:'trade',question:'inspect BTC',symbol:'BTC'});
  assert.equal(parseDeskInput('@sre inspect coverage','ETH').symbol,'ETH');
  assert.throws(()=>parseDeskInput('/sre inspect','BTC'),/try @sre/);
  assert.throws(()=>parseDeskInput('@sre inspect','DOGE'),/Select BTC/);
});
test('direct tools enforce their asset scope and reject accidental extra arguments',()=>{
  for (const c of ['/predict']) {
    assert.equal(parseDeskInput(c+' BTC','ETH').symbol,'BTC');
    assert.equal(parseDeskInput(c,'ETH').symbol,'ETH');
    assert.throws(()=>parseDeskInput(c,'SOL'),/BTC or ETH/);
    assert.throws(()=>parseDeskInput(c+' BTC nonsense'),/Use/);
  }
  // Production-disabled; the parser must no longer expose the preserved anomaly implementation.
  assert.throws(()=>parseDeskInput('/anomaly BTC','BTC'),/Unknown command/);
  assert.throws(()=>parseDeskInput('/drift BTC','BTC'),/Unknown command/);
});
test('command errors do not silently fall into legacy LLM',()=>{
  for (const c of ['@ops hi','/unknown','@trade','@sre','/tools extra']) assert.throws(()=>parseDeskInput(c));
  assert.equal(parseDeskInput('/tools').kind,'tools');
  assert.match(toolHelp(),/Contracts/);
});
