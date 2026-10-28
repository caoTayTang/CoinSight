import GithubSlugger from 'github-slugger';
import { unified } from 'unified';
import remarkParse from 'remark-parse';

// The handbook as a numbered tree: chapters I–VI, pages I.1, and a third level where a topic has parts (IV.1.2).
// One page per topic. Pages not listed here are research notes and go to the collapsed Archive.
export const tree = [
  { title: 'Bắt đầu', items: [
    { path: 'docs/current_progress.md', title: 'CoinSight là gì' },
    { path: 'docs/running_system.md', title: 'Chạy hệ thống' },
    { path: 'docs/desk_commands.md', title: 'Dùng Desk' },
  ] },
  { title: 'Nền tảng dữ liệu', items: [
    { path: 'docs/data_flow.md', title: 'Luồng dữ liệu' },
    { path: 'docs/dw_design.md', title: 'Schema kho & marts' },
    { path: 'docs/data_contracts_v1.md', title: 'Giao ước dữ liệu & API' },
    { path: 'docs/warehouse_proof.md', title: 'Kiểm chứng kho dữ liệu' },
  ] },
  { title: 'Agent AI', items: [
    { path: 'docs/code_guide.md', title: 'Kiến trúc & bản đồ code' },
    { path: 'docs/agent_contracts.md', title: 'Tool & giao ước agent' },
    { path: 'docs/agent_skills.md', title: 'Skills' },
    { path: 'docs/model_router.md', title: 'Model, router & giới hạn' },
    { path: 'docs/response_guardrails.md', title: 'Bằng chứng & guardrail' },
    { path: 'docs/evaluation.md', title: 'Đánh giá agent' },
    { path: 'docs/rag.md', title: 'RAG (kế hoạch)' },
  ] },
  { title: 'Mô hình dự báo', items: [
    { title: 'Dự báo theo giờ', items: [
      { path: 'docs/hourly_forecast_contract.md', title: 'Giao ước' },
      { path: 'docs/forecasting_result.md', title: 'Kết quả' },
    ] },
    { path: 'docs/dss_contract_v1.md', title: 'Mô hình hướng ngày' },
    { path: 'docs/model_integration.md', title: 'Gắn một mô hình mới' },
    { path: 'docs/serving.md', title: 'Tự host model (vLLM, Modal)' },
  ] },
  { title: 'Vận hành', items: [
    { path: 'docs/home_server.md', title: 'Home server & deploy' },
    { path: 'docs/auth_setup.md', title: 'Đăng nhập (Supabase)' },
    { path: 'docs/deployment.md', title: 'CI/CD & rollback' },
    { path: 'docs/observability.md', title: 'Tracing (Jaeger)' },
    { path: 'docs/admin_console.md', title: 'Admin console' },
  ] },
  { title: 'Dự án', items: [
    { path: 'docs/product_readiness.md', title: 'Giới hạn & việc tiếp theo' },
    { path: 'docs/privacy.md', title: 'Quyền riêng tư' },
  ] },
];
export const ARCHIVE = 'Lưu trữ nghiên cứu';
const ROMAN = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X'];

// Every listed page with its number and place: { number: 'IV.1.2', chapter: 'Mô hình dự báo', parent: 'Dự báo theo giờ' }.
function numbered() {
  const out = new Map();
  tree.forEach((chapter, c) => chapter.items.forEach((item, i) => {
    const number = `${ROMAN[c]}.${i + 1}`;
    if (item.items) item.items.forEach((sub, j) =>
      out.set(sub.path, { title: sub.title, number: `${number}.${j + 1}`, chapter: chapter.title, chapterNumber: ROMAN[c], parent: item.title }));
    else out.set(item.path, { title: item.title, number, chapter: chapter.title, chapterNumber: ROMAN[c] });
  }));
  return out;
}
const placed = numbered();
export const chapterNumber = (c) => ROMAN[c];

// Merged topics: an old file or URL resolves to the page that now owns the topic.
export const aliases = {
  'README.md': 'docs/current_progress.md',
  'docs/data_warehouse.md': 'docs/dw_design.md',
  'docs/frontend_progress.md': 'docs/product_readiness.md',
  'docs/repo_guide.md': 'docs/code_guide.md',
  'docs/roadmap.md': 'docs/product_readiness.md',
  'docs/agent_control.md': 'docs/running_system.md',
  'docs/model_evidence.md': 'docs/forecasting_result.md',
};
const urlFor = path => '/docs/' + (path === 'README.md' ? 'overview' : path.replace(/^docs\//, '').replace(/\.md$/, '').replaceAll('_', '-').replaceAll('/', '--').toLowerCase());
export const legacyUrls = Object.fromEntries(Object.entries(aliases).map(([oldPath, newPath]) => [urlFor(oldPath), urlFor(newPath)]));
export function textOf(node) {
  return node.value ?? (node.children || []).map(textOf).join('');
}
const MANUAL_NUMBER = /^\s*(?:[IVX]+\.|\d+(?:\.\d+)*\.?)\s+/;
// Anchor ids come from the heading as written, so existing links keep working. With `numbered`, h2/h3 lose any
// hand-written number ("## 3. Foo") and get one from their position ("3", "3.2"), so numbering is always in order.
export function headingPlugin({ numbered = false } = {}) {
  return (tree) => {
    const slugger = new GithubSlugger();
    const count = [0, 0];
    const visit = (node) => {
      if (node.type === 'heading') {
        node.data = { ...node.data, hProperties: { id: slugger.slug(textOf(node)) } };
        if (numbered && (node.depth === 2 || node.depth === 3)) {
          if (node.depth === 2) { count[0] += 1; count[1] = 0; } else count[1] += 1;
          const label = node.depth === 2 ? `${count[0]}` : `${count[0]}.${count[1]}`;
          const first = node.children?.[0];
          if (first?.type === 'text') first.value = first.value.replace(MANUAL_NUMBER, '');
          node.children = [{ type: 'text', value: `${label} ` }, ...(node.children || [])];
          node.data.hProperties.className = 'numbered';
        }
      }
      node.children?.forEach(visit);
    };
    visit(tree);
  };
}
export function headings(markdown, numbered = false) {
  const tree = unified().use(remarkParse).parse(markdown);
  headingPlugin({ numbered })(tree);
  return tree.children.filter((n) => n.type === 'heading' && n.depth > 1 && n.depth < 4)
    .map((n) => ({ id: n.data.hProperties.id, title: textOf(n), depth: n.depth }));
}
export function makePages(sources) {
  const order = [...placed.keys()];
  return sources.filter((source) => !aliases[source.path]).map((source) => {
    const frontmatter = source.content.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n/);
    const raw = frontmatter ? source.content.slice(frontmatter[0].length) : source.content;
    const place = placed.get(source.path);
    // Listed pages show their numbered title from the tree; the file's own H1 would repeat it.
    const content = place ? raw.replace(/^\s*# .+\r?\n/, '') : raw;
    const title = place?.title || raw.match(/^# (.+)/m)?.[1] || source.path;
    return {
      ...source, content, metadata: frontmatter?.[1], title, url: urlFor(source.path), headings: headings(content, Boolean(place)),
      ...(place || { chapter: ARCHIVE }), archived: !place, rank: place ? order.indexOf(source.path) : order.length,
    };
  }).sort((a, b) => a.rank - b.rank || a.title.localeCompare(b.title));
}
// Repository files that are not documentation pages link to GitHub. Override per build with VITE_REPO_BLOB_URL.
const repoBlob = import.meta.env?.VITE_REPO_BLOB_URL || 'https://github.com/caoTayTang/CoinSight/blob/main';
export function docLink(href, currentPath, pages) {
  if (href === '/') return href;
  if (!href || href.startsWith('#') || /^(https?:|mailto:)/i.test(href)) return href;
  if (href.startsWith('/reports/')) return (import.meta.env?.BASE_URL || '/').replace(/\/$/, '') + href;
  if (href.startsWith('/docs/') || href === '/docs') return href;
  const target = new URL(href, `https://repo.local/${currentPath}`);
  const path = decodeURIComponent(target.pathname.slice(1));
  const page = pages.find((p) => p.path === (aliases[path] || path));
  return page ? page.url + (aliases[path] ? '' : target.hash) : `${repoBlob}/${path.split('/').map(encodeURIComponent).join('/')}${target.hash}`;
}
export function searchPages(pages, query, includeArchive = false) {
  const normalize = (s) => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replaceAll('đ', 'd').toLowerCase();
  const words = normalize(query).trim().split(/\s+/).filter(Boolean);
  return words.length ? pages.filter((p) => (includeArchive || !p.archived) && words.every((w) => normalize(`${p.title} ${p.content}`).includes(w))) : [];
}
