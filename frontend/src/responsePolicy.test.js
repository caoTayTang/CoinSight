import test from 'node:test';
import assert from 'node:assert/strict';
import {JSDOM} from 'jsdom';
import createDOMPurify from 'dompurify';
import {safeResponseUrl,secretLike,redactResponse,diagramPolicy,SVG_SANITIZE,evidenceCharts} from './responsePolicy.js';

test('links permit docs/http but reject scripts, protocol-relative, credentials and token queries',()=>{
  assert.equal(safeResponseUrl('/docs/code-guide'),'/docs/code-guide');
  assert.equal(safeResponseUrl('https://example.com/data'),'https://example.com/data');
  for(const u of ['javascript:alert(1)','data:text/html,hi','//evil.com','https://user:pass@host/a','https://host/a?api_key=secret','https://host/a?TOKEN=x','https:\\evil.com','/api/admin','java\nscript:alert(1)'])assert.equal(safeResponseUrl(u),undefined,u);
});
test('credential-looking input/output are caught without rendering the key',()=>{
  const key='gsk_'+'a'.repeat(30);
  assert.ok(secretLike('hello '+key));assert.ok(!secretLike('What is an API key?'));
  assert.equal(redactResponse('key '+key),'key [credential redacted]');
});
test('safe diagram subset and bounds are enforced',()=>{
  assert.ok(diagramPolicy('flowchart LR\n A[Input] --> B[Tool]').allowed);
  assert.ok(diagramPolicy('sequenceDiagram\n User->>Trade: Ask').allowed);
  for(const code of ['flowchart LR\n click A "https://evil.com"','%%{init: {"securityLevel":"loose"}}%%\nflowchart LR\nA-->B','flowchart LR\n A[<img src=x>]','flowchart LR\nclassDef a fill:red','pie\n"fake" : 42','flowchart LR\n A@{img: "//evil.example/pixel"}','flowchart LR\n'+('A-->B\n'.repeat(101))]) assert.equal(diagramPolicy(code).allowed,false,code);
});
test('SVG sanitizer strips active content, remote resources and embedded HTML',()=>{
  const purify=createDOMPurify(new JSDOM('').window);
  const dirty='<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script><a href="https://evil"><text>link</text></a><image href="https://evil/track"/><foreignObject><div>html</div></foreignObject><rect onload="alert(1)" width="20" height="10"/><animate attributeName="href" values="javascript:alert(1)"/></svg>';
  const clean=purify.sanitize(dirty,SVG_SANITIZE);
  for(const token of ['<script','<a ','<image','foreignObject','onload','<animate','https://evil'])assert.ok(!clean.includes(token),token);
  assert.ok(clean.includes('<rect'));
});
test('charts use numeric tool evidence, never free-form answer chart claims',()=>{
  const meta={command:'anomaly',answer:'price rose 900%',evidence:{trained:{score:.4,threshold:.6,cutoff:'t'}}};
  const charts=evidenceCharts(meta);
  assert.equal(charts.length,1);assert.deepEqual(charts[0].rows.map(r=>r.value),[.4,.6]);
  assert.deepEqual(evidenceCharts({answer:'chart: [1,2,3]'}),[]);
  assert.deepEqual(evidenceCharts({command:'anomaly',evidence:{trained:{score:'0.4',threshold:.6}}}),[]);
  assert.deepEqual(evidenceCharts({command:'drift',evidence:{data_drift:{bad:'shape'}}}),[]);
});
test('unavailable evidence is not charted; delegated SRE evidence can be charted',()=>{
  const coverage={status:'available',observed_at:'now',rows:[{expected_hours:24,observed_hours:20,missing_hours:4}]};
  const meta={evidence:[{tool:'investigate_warehouse',result:{status:'available',result:{evidence:[{tool:'warehouse_coverage',result:coverage}]}}}]};
  assert.equal(evidenceCharts(meta)[0].rows[2].value,4);
  coverage.status='unavailable';assert.deepEqual(evidenceCharts(meta),[]);
  coverage.status='available';coverage.rows[0].missing_hours=8;assert.deepEqual(evidenceCharts(meta),[]);
});

test('a response cannot launch unlimited diagrams or code blocks',async()=>{
  const {responseLimits}=await import('./responsePolicy.js');
  const tree={type:'root',children:Array.from({length:15},(_,i)=>({type:'code',lang:i<5?'mermaid':'text',value:'flowchart LR\n A-->B'}))};
  responseLimits()(tree);
  assert.equal(tree.children.filter(c=>c.type==='code'&&c.lang==='mermaid').length,2);
  assert.ok(tree.children.filter(c=>c.type==='code').length<=12);
});

test('oversized tables are bounded and the truncation is disclosed',async()=>{
  const {responseLimits}=await import('./responsePolicy.js');
  const table={type:'table',children:Array.from({length:110},()=>({type:'tableRow',children:Array.from({length:15},()=>({type:'tableCell',children:[]}))}))};
  const tree={type:'root',children:[table]};responseLimits()(tree);
  assert.equal(table.children.length,101);assert.equal(table.children[0].children.length,12);
  assert.match(tree.children[1].children[0].value,/Table display limited/);
});

test('trace timelines use observed span offsets and never render free-form timing claims',()=>{
  const charts=evidenceCharts({evidence:[{tool:'inspect_trace',result:{status:'available',trace_id:'a'.repeat(32),
    started_at:'2026-10-20T00:00:00Z',spans:[{service:'coinsight-api',operation:'warehouse.query',offset_ms:3,duration_ms:20,error:true}]}}]});
  assert.equal(charts[0].kind,'timeline');assert.equal(charts[0].rows[0].offset,3);
  assert.equal(charts[0].rows[0].warning,true);assert.equal(charts[0].traceId,'a'.repeat(32));
  assert.deepEqual(evidenceCharts({answer:'Trace took 50ms'}),[]);
});
