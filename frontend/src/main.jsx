import React, { lazy, Suspense } from 'react';
import { createRoot } from 'react-dom/client';
const Page = window.location.pathname === '/docs' || window.location.pathname.startsWith('/docs/')
  ? lazy(() => import('./docs/DocsApp.jsx'))
  : lazy(() => import('./Dashboard.jsx'));

createRoot(document.getElementById('root')).render(<Suspense fallback={<p>Đang tải…</p>}><Page /></Suspense>);
