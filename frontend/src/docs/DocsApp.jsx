import React, { useEffect, useId, useMemo, useState } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import sources from 'virtual:documentation';
import { docLink, groups, headingPlugin, makePages, searchPages } from './navigation';
import './docs.css';

const pages = makePages(sources);
let mermaidPromise;
function loadMermaid() {
  return mermaidPromise ||= import('mermaid').then(({ default: mermaid }) => {
    mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'base',
      themeVariables: { primaryColor: '#e7f3ed', primaryTextColor: '#183a32', primaryBorderColor: '#73978c', lineColor: '#55756c', fontFamily: 'Plus Jakarta Sans, sans-serif' } });
    return mermaid;
  });
}
function Diagram({ code }) {
  const id = `diagram-${useId().replace(/[^a-z0-9]/gi, '')}`;
  const [svg, setSvg] = useState('');
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    loadMermaid().then(async (m) => {
      await document.fonts.ready;
      const result = await m.render(id, code);
      if (active) setSvg(result.svg);
    }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [code, id]);
  return <figure className="docs-diagram">
    {svg ? <div className="diagram-scroll" role="img" aria-label="Sơ đồ luồng dữ liệu" dangerouslySetInnerHTML={{ __html: svg }} /> : <p>{failed ? 'Không render được sơ đồ. Xem mã bên dưới.' : 'Đang vẽ sơ đồ…'}</p>}
    <details><summary>Mã sơ đồ</summary><pre>{code}</pre></details>
  </figure>;
}
function CodeBlock({ children }) {
  const code = children?.props?.children;
  const language = children?.props?.className?.replace('language-', '') || 'text';
  const [copied, setCopied] = useState(false);
  if (language === 'mermaid') return <Diagram code={String(code).trim()} />;
  return <div className="docs-code"><div className="code-toolbar"><span>{language}</span><button onClick={async () => {
    try { await navigator.clipboard.writeText(String(code)); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { setCopied(false); }
  }}>{copied ? 'Đã copy' : 'Copy'}</button></div><pre>{children}</pre></div>;
}

export default function DocsApp() {
  const path = window.location.pathname.replace(/\/$/, '');
  const page = path === '/docs' ? pages[0] : pages.find((p) => p.url === path);
  const [query, setQuery] = useState('');
  const [menu, setMenu] = useState(false);
  const results = useMemo(() => searchPages(pages, query), [query]);
  const index = pages.indexOf(page);
  useEffect(() => {
    document.documentElement.lang = 'vi';
    document.title = `${page?.title || 'Không tìm thấy trang'} — CoinSight Docs`;
    if (window.location.hash) requestAnimationFrame(() => document.getElementById(decodeURIComponent(window.location.hash.slice(1)))?.scrollIntoView());
  }, [page]);
  const components = useMemo(() => ({
    pre: CodeBlock,
    table: ({ children }) => <div className="docs-table"><table>{children}</table></div>,
    a: ({ href, children }) => {
      const target = docLink(href, page?.path || 'README.md', pages);
      return <a href={target} {...(/^https?:/.test(target || '') ? { target: '_blank', rel: 'noreferrer' } : {})}>{children}</a>;
    },
  }), [page]);
  return <div className="docs-shell">
    <a className="docs-skip" href="#docs-content">Đến nội dung</a>
    <header className="docs-header"><a className="docs-brand" href="/docs/">CoinSight<span> / </span><b>Docs</b></a>
      <div className="docs-header-actions"><span className="docs-version">System handbook</span><a href="/">Mở dashboard ↗</a><button className="docs-menu" aria-expanded={menu} aria-controls="docs-sidebar" onClick={() => setMenu(!menu)}>Mục lục</button></div>
    </header>
    <aside id="docs-sidebar" className={`docs-sidebar ${menu ? 'is-open' : ''}`}>
      <label className="docs-search"><span>Tìm trong tài liệu</span><input type="search" placeholder="Kafka, train, cách chạy…" value={query} onChange={(e) => setQuery(e.target.value)} /></label>
      {query.trim() ? <div className="docs-results"><p role="status">{results.length} trang phù hợp</p>{results.map((p) => <a href={p.url} key={p.path}><strong>{p.title}</strong><small>{p.group}</small></a>)}{!results.length && <p>Thử từ khóa khác hoặc bỏ dấu tiếng Việt.</p>}</div>
        : <nav aria-label="Tài liệu hệ thống">{groups.map((group) => <section key={group}><h2>{group}</h2>{pages.filter((p) => p.group === group).map((p) => <a key={p.path} href={p.url} aria-current={page === p ? 'page' : undefined}>{p.title}</a>)}</section>)}</nav>}
      <div className="docs-sidebar-foot">{pages.length} tài liệu · CoinSight<br />Data warehouse & decision support</div>
    </aside>
    <main id="docs-content" className="docs-main" tabIndex={-1}>
      {page ? <><div className="docs-breadcrumb">Tài liệu <span>/</span> {page.group}</div>
        <div className="docs-page-meta"><span>{page.title}</span><span>{Math.max(1, Math.ceil(page.content.split(/\s+/).length / 220))} phút đọc</span></div>
        <article className="docs-prose">{!/^# /m.test(page.content) && <h1>{page.title}</h1>}<Markdown remarkPlugins={[remarkGfm, headingPlugin]} components={components} skipHtml>{page.content}</Markdown>
          {page.metadata && <details><summary>Thông số tài liệu (YAML)</summary><pre>{page.metadata}</pre></details>}
        </article>
        <nav className="docs-pagination" aria-label="Chuyển trang">{index > 0 ? <a href={pages[index - 1].url}><small>← Trang trước</small>{pages[index - 1].title}</a> : <span />}{index < pages.length - 1 && <a href={pages[index + 1].url}><small>Trang tiếp →</small>{pages[index + 1].title}</a>}</nav>
      </> : <article className="docs-prose"><h1>Không tìm thấy trang</h1><p>Đường dẫn này chưa có trong bộ tài liệu.</p><a href="/docs/">Về luồng dữ liệu →</a></article>}
      <footer className="docs-footer">CoinSight · Tài liệu hệ thống<a href="#docs-content">Lên đầu ↑</a></footer>
    </main>
    <aside className="docs-toc"><h2>Trong trang này</h2><nav aria-label="Mục lục trang">{page?.headings.map((h) => <a key={h.id} className={h.depth === 3 ? 'subheading' : ''} href={`#${h.id}`}>{h.title}</a>)}</nav><p>Nội dung phản ánh tài liệu trong bản build hiện tại.</p></aside>
  </div>;
}
