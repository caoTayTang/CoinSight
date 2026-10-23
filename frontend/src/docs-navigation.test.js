import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ARCHIVE, docLink, headings, legacyUrls, makePages, searchPages } from './docs/navigation.js';

const pages = makePages([
  { path: 'README.md', content: '# Tổng quan\nLuồng dữ liệu' },
  { path: 'docs/current_progress.md', content: '# Bắt đầu\nTổng quan' },
  { path: 'docs/data_flow.md', content: '# Luồng dữ liệu\nKafka và PostgreSQL' },
  { path: 'docs/future/new_page.md', content: '# New document' },
]);
test('relative Markdown links resolve across directories and preserve anchors', () => {
  assert.equal(docLink('../README.md#test', 'docs/data_flow.md', pages), '/docs/current-progress');
  assert.equal(docLink('docs/data_flow.md', 'README.md', pages), '/docs/data-flow');
  assert.equal(docLink('/', 'docs/current_progress.md', pages), '/');
  assert.equal(docLink('#trang', 'README.md', pages), '#trang');
  assert.equal(docLink('https://example.com', 'README.md', pages), 'https://example.com');
});

test('research is searchable only on request and merged topic URLs have one destination',()=>{
  const docs=makePages([
    {path:'docs/current_progress.md',content:'# Current'},
    {path:'docs/roadmap.md',content:'# Old roadmap'},
    {path:'docs/product_readiness.md',content:'# Limits'},
    {path:'docs/hourly_tuning.md',content:'# Tuning\nHistorical experiment'},
    {path:'docs/auth_setup.md',content:'# Sign in\nSupabase callback'},
  ]);
  assert.equal(docs.filter(p=>p.path.includes('roadmap')).length,0);
  assert.equal(docs.find(p=>p.path.includes('hourly_tuning')).chapter,ARCHIVE);
  assert.equal(searchPages(docs,'historical').length,0);
  assert.equal(searchPages(docs,'historical',true).length,1);
  assert.equal(searchPages(docs,'supabase callback').length,1);
  assert.equal(legacyUrls['/docs/roadmap'],'/docs/product-readiness');
  assert.equal(legacyUrls['/docs/overview'],'/docs/current-progress');
  assert.equal(legacyUrls['/docs/model-evidence'],'/docs/forecasting-result');
  assert.equal(docLink('roadmap.md','docs/current_progress.md',docs),'/docs/product-readiness');
});
test('new Markdown pages are included and search supports Vietnamese without accents', () => {
  assert.ok(pages.some((p) => p.path === 'docs/future/new_page.md'));
  assert.equal(searchPages(pages, 'luong du lieu kafka').length, 1);
  assert.equal(searchPages(pages, 'khong ton tai').length, 0);
});
test('heading anchors ignore fenced code and distinguish duplicate headings', () => {
  const result = headings('# Title\n## Luồng dữ liệu\n```text\n## Fake\n```\n## Luồng dữ liệu\n');
  assert.deepEqual(result.map((h) => h.id), ['luồng-dữ-liệu', 'luồng-dữ-liệu-1']);
});
test('merged documents have one page and old Markdown links point to the canonical page', () => {
  const canonical = makePages([
    { path: 'docs/dw_design.md', content: '# Kho dữ liệu' },
    { path: 'docs/data_warehouse.md', content: '# Bản tóm tắt cũ' },
  ]);
  assert.equal(canonical.length, 1);
  assert.equal(docLink('data_warehouse.md#old', 'docs/data_flow.md', canonical), '/docs/dw-design');
});

test('current progress is first and agent guides resolve within docs', () => {
  const guides = makePages([
    {path:'docs/current_progress.md',content:'# Current\n## 1. Bốn phần cần phân biệt'},
    {path:'docs/data_flow.md',content:'# Data flow'},
    {path:'docs/agent_control.md',content:'# Controls'},
    {path:'docs/model_router.md',content:'# Router'},
    {path:'docs/code_guide.md',content:'# Code'},
    {path:'docs/agent_contracts.md',content:'# Contracts'},
  ]);
  assert.equal(guides[0].path,'docs/current_progress.md');
  assert.equal(docLink('model_router.md','docs/current_progress.md',guides),'/docs/model-router');
  assert.equal(docLink('agent_contracts.md','docs/code_guide.md',guides),'/docs/agent-contracts');
  assert.equal(guides[0].headings[0].id,'1-bốn-phần-cần-phân-biệt');
  assert.equal(guides[0].headings[0].title,'1 Bốn phần cần phân biệt');
});

test('pages are numbered by their place in the tree, sub-pages included', () => {
  const docs = makePages([
    { path: 'docs/forecasting_result.md', content: '# Old title\nBody' },
    { path: 'docs/evaluation.md', content: '# Agent evaluation\n## 3. Results\n### Something\n## How it works' },
    { path: 'docs/current_progress.md', content: '# X' },
  ]);
  assert.deepEqual(docs.map(p => p.number), ['I.1', 'III.6', 'IV.1.2']);
  const result = docs.find(p => p.path === 'docs/forecasting_result.md');
  assert.equal(result.parent, 'Dự báo theo giờ');
  assert.ok(!result.content.includes('Old title'));  // the tree's numbered title replaces the file's H1
  const evaluation = docs.find(p => p.path === 'docs/evaluation.md');
  assert.deepEqual(evaluation.headings.map(h => h.title), ['1 Results', '1.1 Something', '2 How it works']);
  assert.equal(evaluation.headings[0].id, '3-results');  // anchors keep the written text, so old links work
});
