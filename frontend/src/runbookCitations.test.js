import test from 'node:test';
import assert from 'node:assert/strict';
import {unified} from 'unified';
import remarkParse from 'remark-parse';
import {runbookSources,citationLinks} from './runbookCitations.js';

const hit={citation:'[runbook:feature_drift:1:0]',title:'PSI reference',source:'warehouse_agents/knowledge/feature_drift.md',
  sha256:'a'.repeat(64),text:'PSI is not accuracy.'};
const retrieval={tool:'search_runbooks',result:{status:'available',hits:[hit,hit]}};
test('sources require retrieved evidence, deduplicate IDs and traverse A2A delegation',()=>{
  assert.deepEqual(runbookSources([retrieval]),[hit]);
  assert.deepEqual(runbookSources([{tool:'investigate_warehouse',result:{result:{evidence:[retrieval]}}}]),[hit]);
  assert.deepEqual(runbookSources([{...retrieval,result:{status:'unavailable',hits:[hit]}}]),[]);
  assert.deepEqual(runbookSources([{tool:'unrelated',result:retrieval.result}]),[]);
  assert.deepEqual(runbookSources([{...retrieval,result:{status:'available',hits:[{...hit,sha256:'bad'}]}}]),[]);
});
test('only known citations become links; code, existing links and unknown IDs stay untouched',()=>{
  const parser=unified().use(remarkParse);
  const tree=parser.parse(`Read **${hit.citation}**. [runbook:unknown:0:0]\n\n\`${hit.citation}\`\n\n[${hit.citation}](https://example.com)\n\n\`\`\`text\n${hit.citation}\n\`\`\``);
  citationLinks(new Map([[hit.citation,'#source-1']]))()(tree);
  const links=[];
  const walk=n=>{if(n.type==='link')links.push(n.url);n.children?.forEach(walk);};walk(tree);
  assert.deepEqual(links,['#source-1','https://example.com']);
  assert.equal(tree.children[1].children[0].type,'inlineCode');
  assert.equal(tree.children.at(-1).type,'code');
  assert.match(tree.children[0].children.at(-1).value,/runbook:unknown/);
});
