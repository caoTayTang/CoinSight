import { test } from 'node:test';
import assert from 'node:assert/strict';
import { docLink, headings, makePages, searchPages } from './docs/navigation.js';

const pages = makePages([
  { path: 'README.md', content: '# Tổng quan\nLuồng dữ liệu' },
  { path: 'docs/data_flow.md', content: '# Luồng dữ liệu\nKafka và PostgreSQL' },
  { path: 'docs/future/new_page.md', content: '# New document' },
]);
test('relative Markdown links resolve across directories and preserve anchors', () => {
  assert.equal(docLink('../README.md#test', 'docs/data_flow.md', pages), '/docs/overview#test');
  assert.equal(docLink('docs/data_flow.md', 'README.md', pages), '/docs/data-flow');
  assert.equal(docLink('/', 'docs/current_progress.md', pages), '/');
  assert.equal(docLink('#trang', 'README.md', pages), '#trang');
  assert.equal(docLink('https://example.com', 'README.md', pages), 'https://example.com');
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
});
