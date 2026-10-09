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
