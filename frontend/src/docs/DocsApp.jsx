import React, { useEffect, useMemo, useState } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import sources from 'virtual:documentation';
import { ARCHIVE, chapterNumber, docLink, headingPlugin, legacyUrls, makePages, searchPages, tree } from './navigation';
import './docs.css';
import Diagram from './Diagram';
import ThemeToggle from '../ThemeToggle.jsx';

const pages = makePages(sources);
const byPath = Object.fromEntries(pages.map((p) => [p.path, p]));
const numberedHeadings = [headingPlugin, { numbered: true }];

// One sidebar link: "III.6  Đánh giá agent".
function NavLink({ item, current }) {
  const page = byPath[item.path];
  if (!page) return null;
  return <a href={page.url} aria-current={current === page ? 'page' : undefined}><span className="docs-num">{page.number}</span>{page.title}</a>;
}

function Toc({ current }) {
  return <nav aria-label="Tài liệu hệ thống" className="docs-tree">
    {tree.map((chapter, c) => <details key={chapter.title} open>
      <summary><span className="docs-num">{chapterNumber(c)}</span>{chapter.title}</summary>
      {chapter.items.map((item, i) => item.items
        ? <div key={item.title} className="docs-subgroup"><p><span className="docs-num">{chapterNumber(c)}.{i + 1}</span>{item.title}</p>
          {item.items.map((sub) => <NavLink key={sub.path} item={sub} current={current} />)}</div>
        : <NavLink key={item.path} item={item} current={current} />)}
    </details>)}
    <details className="docs-archive" open={current?.archived || undefined}>
      <summary>{ARCHIVE} <small>{pages.filter((p) => p.archived).length}</small></summary>
      <p>Thí nghiệm và ghi chú cũ; có thể không còn đúng với code hiện tại.</p>
      {pages.filter((p) => p.archived).map((p) => <a key={p.path} href={p.url} aria-current={current === p ? 'page' : undefined}>{p.title}</a>)}
    </details>
  </nav>;
}
function CodeBlock({ children }) {
  const code = children?.props?.children;
  const language = children?.props?.className?.replace('language-', '') || 'văn bản';
  const [copied, setCopied] = useState(false);
  if (language === 'mermaid') return <Diagram code={String(code).trim()} />;
  return <div className="docs-code"><div className="code-toolbar"><span>{language}</span><button onClick={async () => {
    try { await navigator.clipboard.writeText(String(code)); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { setCopied(false); }
  }}>{copied ? 'Đã sao chép' : 'Sao chép'}</button></div><pre>{children}</pre></div>;
}

export default function DocsApp() {
  const path = window.location.pathname.replace(/\/$/, '');
  const resolvedPath = legacyUrls[path] || path;
  const page = resolvedPath === '/docs' ? pages.find((p) => p.path === 'docs/current_progress.md') || pages[0] : pages.find((p) => p.url === resolvedPath);
  const [query, setQuery] = useState('');
  const [menu, setMenu] = useState(false);
  const [includeArchive, setIncludeArchive] = useState(false);
  const results = useMemo(() => searchPages(pages, query, includeArchive), [query, includeArchive]);
  const siblings = pages.filter(p => p.archived === Boolean(page?.archived));
  const index = siblings.indexOf(page);
  const currentCount = pages.filter(p => !p.archived).length;
  const heading = page && (page.number ? `${page.number} ${page.title}` : page.title);
  useEffect(() => {
    if (legacyUrls[path]) { window.location.replace(legacyUrls[path]); return; }
    document.documentElement.lang = 'vi';
    document.title = `${heading || 'Không tìm thấy trang'} — Tài liệu CoinSight`;
    if (window.location.hash) requestAnimationFrame(() => document.getElementById(decodeURIComponent(window.location.hash.slice(1)))?.scrollIntoView());
  }, [page, path]);
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
    <header className="docs-header"><a className="docs-brand" href="/docs/"><img className="docs-brand-mark" src={`${import.meta.env.BASE_URL}logo.svg`} alt="" aria-hidden="true" />CoinSight<span> / </span><b>Tài liệu</b></a>
      <div className="docs-header-actions"><span className="docs-version">Sổ tay hệ thống</span><ThemeToggle /><a href="/">Thị trường ↗</a><button className="docs-menu" aria-expanded={menu} aria-controls="docs-sidebar" onClick={() => setMenu(!menu)}>Mục lục</button></div>
    </header>
    <aside id="docs-sidebar" className={`docs-sidebar ${menu ? 'is-open' : ''}`}>
      <label className="docs-search"><span>Tìm trong tài liệu</span><input type="search" placeholder="Đăng nhập, deploy, evaluation…" value={query} onChange={(e) => setQuery(e.target.value)} /></label>
      <label className="docs-search-archive"><input type="checkbox" checked={includeArchive} onChange={e=>setIncludeArchive(e.target.checked)}/> Tìm cả tài liệu lưu trữ</label>
      {query.trim() ? <div className="docs-results"><p role="status">{results.length} trang phù hợp</p>{results.map((p) => <a href={p.url} key={p.path}><strong>{p.number ? `${p.number} ` : ''}{p.title}</strong><small>{p.parent ? `${p.chapter} / ${p.parent}` : p.chapter}</small></a>)}{!results.length && <p>Thử từ khóa khác hoặc bỏ dấu tiếng Việt.</p>}</div>
        : <Toc current={page} />}
      <div className="docs-sidebar-foot">{currentCount} hướng dẫn · {pages.length-currentCount} tài liệu lưu trữ<br />Một trang chính cho mỗi chủ đề</div>
    </aside>
    <main id="docs-content" className="docs-main" tabIndex={-1}>
      {page ? <><div className="docs-breadcrumb">{page.archived ? ARCHIVE : <>{page.chapterNumber} · {page.chapter}{page.parent && <><span>/</span>{page.parent}</>}</>}</div>
        <div className="docs-page-meta"><span>{Math.max(1, Math.ceil(page.content.split(/\s+/).length / 220))} phút đọc</span></div>
        {page.archived&&<aside className="docs-archive-notice"><strong>Tài liệu lưu trữ</strong><p>Giữ lại để truy nguyên thí nghiệm và quyết định trước đây. Nội dung có thể không phản ánh code hoặc deployment hiện tại. <a href="/docs/">Mở hướng dẫn hiện tại →</a></p></aside>}
        <article className={`docs-prose${page.archived ? '' : ' is-numbered'}`}>{!page.archived ? <h1><span className="docs-num">{page.number}</span>{page.title}</h1> : !/^# /m.test(page.content) && <h1>{page.title}</h1>}<Markdown remarkPlugins={[remarkGfm, page.archived ? headingPlugin : numberedHeadings]} components={components} skipHtml>{page.content}</Markdown>
          {page.metadata && <details><summary>Thông số tài liệu (YAML)</summary><pre>{page.metadata}</pre></details>}
        </article>
        {page.path==='docs/current_progress.md'&&<section className="docs-start" aria-label="Chọn hướng dẫn">
          <div className="docs-start-label">BẮT ĐẦU TỪ ĐÂY</div>
          <div className="docs-start-grid">
            <a href="/docs/running-system"><b>I.2</b><strong>Chạy hệ thống</strong><span>Docker Compose, nạp dữ liệu, kiểm tra</span></a>
            <a href="/docs/desk-commands"><b>I.3</b><strong>Dùng Desk</strong><span>Hỏi agent, lệnh, lịch sử và ghi nhớ</span></a>
            <a href="/docs/evaluation"><b>III.6</b><strong>Đánh giá agent</strong><span>Kho dữ liệu làm đáp án, kết quả v0–v4</span></a>
            <a href="/docs/home-server"><b>V.1</b><strong>Home server</strong><span>Tunnel, deploy tự động, kiểm tra</span></a>
          </div>
        </section>}
        <nav className="docs-pagination" aria-label="Chuyển trang">{index > 0 ? <a href={siblings[index - 1].url}><small>← Trang trước</small>{siblings[index - 1].number} {siblings[index - 1].title}</a> : <span />}{index < siblings.length - 1 && <a href={siblings[index + 1].url}><small>Trang tiếp →</small>{siblings[index + 1].number} {siblings[index + 1].title}</a>}</nav>
      </> : <article className="docs-prose"><h1>Không tìm thấy trang</h1><p>Đường dẫn này chưa có trong bộ tài liệu.</p><a href="/docs/">Về tổng quan hệ thống →</a></article>}
      <footer className="docs-footer">CoinSight · Tài liệu hệ thống<a href="#docs-content">Lên đầu ↑</a></footer>
    </main>
    <aside className="docs-toc"><h2>Trong trang này</h2><nav aria-label="Mục lục trang">{page?.headings.map((h) => <a key={h.id} className={h.depth === 3 ? 'subheading' : ''} href={`#${h.id}`}>{h.title}</a>)}</nav><p>Nội dung phản ánh tài liệu trong bản build hiện tại.</p></aside>
  </div>;
}
