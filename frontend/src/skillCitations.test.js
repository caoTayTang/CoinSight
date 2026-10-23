import test from 'node:test';
import assert from 'node:assert/strict';
import {unified} from 'unified';
import remarkParse from 'remark-parse';
import {skillSources,citationLinks} from './skillCitations.js';

const skill={status:'available',name:'model-drift',description:'Drift and live performance.',instructions:'## Steps\n1. model_health',
  source:'warehouse_agents/skills/model-drift/SKILL.md',sha256:'a'.repeat(64),citation:'[skill:model-drift]'};
const loaded={tool:'load_skill',result:skill};
const hit={citation:skill.citation};
test('sources require a loaded skill, deduplicate and traverse A2A delegation',()=>{
  const [source]=skillSources([loaded,loaded]);
  assert.equal(source.citation,'[skill:model-drift]'); assert.equal(skillSources([loaded,loaded]).length,1);
  assert.equal(skillSources([{tool:'investigate_warehouse',result:{result:{evidence:[loaded]}}}]).length,1);
  assert.deepEqual(skillSources([{...loaded,result:{...skill,status:'unavailable'}}]),[]);
  assert.deepEqual(skillSources([{tool:'unrelated',result:skill}]),[]);
  assert.deepEqual(skillSources([{...loaded,result:{...skill,sha256:'bad'}}]),[]);
});
test('only known citations become links; code, existing links and unknown IDs stay untouched',()=>{
  const parser=unified().use(remarkParse);
  const tree=parser.parse(`Read **${hit.citation}**. [skill:unknown]\n\n\`${hit.citation}\`\n\n[${hit.citation}](https://example.com)\n\n\`\`\`text\n${hit.citation}\n\`\`\``);
  citationLinks(new Map([[hit.citation,'#source-1']]))()(tree);
  const links=[];
  const walk=n=>{if(n.type==='link')links.push(n.url);n.children?.forEach(walk);};walk(tree);
  assert.deepEqual(links,['#source-1','https://example.com']);
  assert.equal(tree.children[0].children[1].children[0].children[0].value,'Model drift');
  assert.equal(tree.children[1].children[0].type,'inlineCode');
  assert.equal(tree.children.at(-1).type,'code');
  assert.match(tree.children[0].children.at(-1).value,/skill:unknown/);
});
