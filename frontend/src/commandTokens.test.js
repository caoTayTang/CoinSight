import test from 'node:test';
import assert from 'node:assert/strict';
import {unified} from 'unified';
import remarkParse from 'remark-parse';
import {splitCommands,commandLinks,COMMAND_HREF} from './commandTokens.js';

test('only real agents and commands are split out',()=>{
  assert.deepEqual(splitCommands('@sre check BTC, then /predict.').map(p=>p.token||p),['@sre',' check BTC, then ','/predict','.']);
  assert.deepEqual(splitCommands('@foo /bar mail@sre.io a/sre'),['@foo /bar mail@sre.io a/sre']);
  assert.equal(splitCommands('/SRE x')[0].token,'/SRE');
});
test('answers: tokens in text or alone in inline code become chips; code blocks and links stay',()=>{
  const tree=unified().use(remarkParse).parse('Use **`@trade`** or `@sre phân tích` and /tools.\n\n```\n@sre\n```\n\n[@sre](https://x.y)');
  commandLinks()(tree);
  const urls=[];const walk=n=>{if(n.type==='link')urls.push(n.url);n.children?.forEach(walk);};walk(tree);
  assert.deepEqual(urls,[COMMAND_HREF+'@trade',COMMAND_HREF+'/tools','https://x.y']);
});
