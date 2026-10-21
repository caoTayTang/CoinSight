import React, { lazy, Suspense } from 'react';
import { createRoot } from 'react-dom/client';
import './themes.css';
// `vite build --mode docs` ships the documentation alone, for static hosting without the API.
const docsOnly = import.meta.env.MODE === 'docs';
const isDocs = window.location.pathname === '/docs' || window.location.pathname.startsWith('/docs/');
if (docsOnly && window.location.pathname === '/') window.location.replace('/docs/');
const Page = docsOnly || isDocs
  ? lazy(() => import('./docs/DocsApp.jsx'))
  : lazy(() => import('./Dashboard.jsx'));

createRoot(document.getElementById('root')).render(<Suspense fallback={<p>Đang tải…</p>}><Page /></Suspense>);
