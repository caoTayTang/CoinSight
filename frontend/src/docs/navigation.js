import GithubSlugger from 'github-slugger';
import { unified } from 'unified';
import remarkParse from 'remark-parse';

export const groups = ['Bắt đầu', 'Kho dữ liệu', 'Mô hình & giao ước', 'Vận hành', 'Giao diện'];
export const aliases = {
  'docs/data_warehouse.md': 'docs/dw_design.md',
  'docs/frontend_progress.md': 'docs/product_readiness.md',
};
export const legacyUrls = { '/docs/data-warehouse': '/docs/dw-design', '/docs/frontend-progress': '/docs/product-readiness' };
const catalog = {
  'docs/evaluation.md': ['Agent evaluation · results', groups[0], -3.5],
  'docs/serving.md': ['Self-hosted serving · benchmark', groups[3], -2],
  'docs/forecasting_result.md': ['Hourly forecasting · honest result', groups[2], -2],
  'docs/model_integration.md': ['Integrating a forecasting model', groups[2], -1.5],
  'docs/home_server.md': ['Home server: tunnel, stack, deploys', groups[3], -2],
  'docs/privacy.md': ['Privacy', groups[3], 9],
  'docs/model_evidence.md': ['Models & evidence · results and effort', groups[0], -2.75],
  'docs/sre_rag.md': ['SRE: retrieval, drift & fine-tune', groups[0], -0.6],
  'docs/current_progress.md': ['Bắt đầu: hệ thống hiện tại', groups[0], -3],
  'docs/desk_commands.md': ['Desk: @trade / @sre /tool', groups[0], -2.5],
  'docs/agent_control.md': ['Điều khiển agent & tool', groups[0], -2],
  'docs/model_router.md': ['Chọn model, key & router', groups[0], -1],
  'docs/response_guardrails.md': ['Response, graph & guardrail', groups[0], -0.75],
  'docs/code_guide.md': ['Đọc code theo một request', groups[0], -0.5],
  'docs/agent_contracts.md': ['Contract model, tool & agent', groups[2], -1],
  'docs/local_agents.md': ['Bộ dự báo MCP/A2A · không LLM', groups[3], -1],
  'docs/data_flow.md': ['Luồng dữ liệu', groups[0], 0],
  'README.md': ['Overview (English)', groups[0], -4],
  'docs/repo_guide.md': ['Giới thiệu & cấu trúc repo', groups[0], 1],
  'docs/running_system.md': ['Chạy và kiểm tra hệ thống', groups[0], 2],
  'docs/demo_script.md': ['Kịch bản demo', groups[0], 3],
  'docs/product_readiness.md': ['Tiến độ & việc còn thiếu', groups[0], 4],
  'docs/roadmap.md': ['Roadmap hoàn thiện', groups[0], 5],
  'docs/dw_design.md': ['Schema & phép tổng hợp', groups[1], 0],
  'docs/warehouse_proof.md': ['Bằng chứng warehouse', groups[1], 1],
  'docs/eda_report.md': ['Đọc hiểu báo cáo EDA', groups[1], 2],
  'docs/data_contracts_v1.md': ['Định dạng dữ liệu & API', groups[2], 0],
  'docs/dss_contract_v1.md': ['Dự đoán hướng ngày · hiện tại', groups[2], 1],
  'docs/hourly_forecast_contract.md': ['Dự báo giá giờ · giao ước', groups[2], 2],
  'docs/model_question.md': ['Bài toán · đầu vào/đầu ra', groups[2], 2.5],
  'docs/hourly_backtest.md': ['BTC giờ · train/backtest', groups[2], 2.6],
  'docs/forecasting_design.md': ['Nghiên cứu mô hình · Dương', groups[2], 3],
  'docs/observability.md': ['Theo dõi với Jaeger', groups[3], 0],
  'docs/deployment.md': ['Triển khai & CI/CD', groups[3], 1],
  'frontend/DESIGN.md': ['Quy tắc thiết kế', groups[4], 0],
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
  return sources.filter((source) => !aliases[source.path]).map((source) => {
    const frontmatter = source.content.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n/);
    const content = frontmatter ? source.content.slice(frontmatter[0].length) : source.content;
    const [title, group, order] = catalog[source.path] || [source.content.match(/^# (.+)/m)?.[1] || source.path, groups[1], 99];
    const slug = source.path === 'README.md' ? 'overview' : source.path.replace(/^docs\//, '').replace(/\.md$/, '').replaceAll('_', '-').replaceAll('/', '--').toLowerCase();
    return { ...source, content, metadata: frontmatter?.[1], title, group, order, url: `/docs/${slug}`, headings: headings(content) };
  }).sort((a, b) => groups.indexOf(a.group) - groups.indexOf(b.group) || a.order - b.order || a.title.localeCompare(b.title));
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
export function searchPages(pages, query) {
  const normalize = (s) => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replaceAll('đ', 'd').toLowerCase();
  const words = normalize(query).trim().split(/\s+/).filter(Boolean);
  return words.length ? pages.filter((p) => words.every((w) => normalize(`${p.title} ${p.content}`).includes(w))) : [];
}
