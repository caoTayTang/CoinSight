import GithubSlugger from 'github-slugger';
import { unified } from 'unified';
import remarkParse from 'remark-parse';

export const groups = ['Bắt đầu', 'Dữ liệu & pipeline', 'Model & contracts', 'Vận hành', 'Giao diện'];
const catalog = {
  'docs/data_flow.md': ['Luồng dữ liệu', groups[0], 0],
  'README.md': ['Tổng quan & chạy hệ thống', groups[0], 1],
  'docs/product_readiness.md': ['Tiến độ & việc còn thiếu', groups[0], 2],
  'docs/data_warehouse.md': ['Kho dữ liệu', groups[1], 0],
  'docs/dw_design.md': ['Thiết kế warehouse', groups[1], 1],
  'docs/data_contracts_v1.md': ['Data contracts', groups[2], 0],
  'docs/dss_contract_v1.md': ['Daily direction · hiện tại', groups[2], 1],
  'docs/hourly_forecast_contract.md': ['Hourly forecast · contract', groups[2], 2],
  'docs/forecasting_design.md': ['Proposal của Dương', groups[2], 3],
  'docs/observability.md': ['Tracing & Jaeger', groups[3], 0],
  'docs/deployment.md': ['Deployment & CI', groups[3], 1],
  'docs/frontend_progress.md': ['Tiến độ giao diện', groups[4], 0],
  'frontend/DESIGN.md': ['Design reference', groups[4], 1],
};
export function textOf(node) {
  return node.value ?? (node.children || []).map(textOf).join('');
}
export function headingPlugin() {
  return (tree) => {
    const slugger = new GithubSlugger();
    const visit = (node) => {
      if (node.type === 'heading') node.data = { ...node.data, hProperties: { id: slugger.slug(textOf(node)) } };
      node.children?.forEach(visit);
    };
    visit(tree);
  };
}
export function headings(markdown) {
  const tree = unified().use(remarkParse).parse(markdown);
  headingPlugin()(tree);
  return tree.children.filter((n) => n.type === 'heading' && n.depth > 1 && n.depth < 4)
    .map((n) => ({ id: n.data.hProperties.id, title: textOf(n), depth: n.depth }));
}
export function makePages(sources) {
  return sources.map((source) => {
    const frontmatter = source.content.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n/);
    const content = frontmatter ? source.content.slice(frontmatter[0].length) : source.content;
    const [title, group, order] = catalog[source.path] || [source.content.match(/^# (.+)/m)?.[1] || source.path, groups[1], 99];
    const slug = source.path === 'README.md' ? 'overview' : source.path.replace(/^docs\//, '').replace(/\.md$/, '').replaceAll('_', '-').replaceAll('/', '--').toLowerCase();
    return { ...source, content, metadata: frontmatter?.[1], title, group, order, url: `/docs/${slug}`, headings: headings(content) };
  }).sort((a, b) => groups.indexOf(a.group) - groups.indexOf(b.group) || a.order - b.order || a.title.localeCompare(b.title));
}
export function docLink(href, currentPath, pages) {
  if (!href || href.startsWith('#') || /^(https?:|mailto:)/i.test(href)) return href;
  if (href.startsWith('/docs/') || href === '/docs') return href;
  const target = new URL(href, `https://repo.local/${currentPath}`);
  const path = decodeURIComponent(target.pathname.slice(1));
  const page = pages.find((p) => p.path === path);
  return page ? page.url + target.hash : `https://github.com/caoTayTang/CoinSight/blob/feature/decision-pipeline-v1/${path.split('/').map(encodeURIComponent).join('/')}${target.hash}`;
}
export function searchPages(pages, query) {
  const normalize = (s) => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replaceAll('đ', 'd').toLowerCase();
  const words = normalize(query).trim().split(/\s+/).filter(Boolean);
  return words.length ? pages.filter((p) => words.every((w) => normalize(`${p.title} ${p.content}`).includes(w))) : [];
}
