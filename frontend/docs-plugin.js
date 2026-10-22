import { copyFileSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve, relative } from 'node:path';

// Explicit public documentation roots. Never walk credentials, data or dependencies.
export function documentationPlugin() {
  const root = resolve(import.meta.dirname, '..');
  const walk = (dir) => readdirSync(dir, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory() ? walk(resolve(dir, entry.name)) : entry.name.endsWith('.md') ? [resolve(dir, entry.name)] : []);
  let mode;
  return {
    name: 'coinsight-documentation',
    configResolved(config) { mode = config.mode; },
    configureServer(server) {
      server.middlewares.use('/reports/hourly-research-summary.html', (req, res, next) => {
        if (req.method !== 'GET' || !['', '/'].includes(req.url.split('?')[0])) return next();
        res.setHeader('Content-Type', 'text/html; charset=utf-8');
        res.end(readFileSync(resolve(root, 'docs/hourly_research_summary.html')));
      });
    },
    generateBundle() {
      this.emitFile({type:'asset', fileName:'reports/hourly-research-summary.html',
        source:readFileSync(resolve(root, 'docs/hourly_research_summary.html'))});
    },
    writeBundle(options) {
      if (mode !== 'docs') return;
      // The docs build goes to dist-docs/docs/; the asset root is dist-docs/. Static hosting rules sit at that root,
      // and unknown paths fall back to its index.html copy, so the docs router shows its own not-found page.
      const site = dirname(options.dir);
      copyFileSync(resolve(options.dir, 'index.html'), resolve(site, 'index.html'));
      writeFileSync(resolve(site, '_headers'), [
        '/*', '  X-Content-Type-Options: nosniff', '  Referrer-Policy: strict-origin-when-cross-origin',
        '  X-Frame-Options: DENY', '/docs/assets/*', '  Cache-Control: public, max-age=31536000, immutable', ''].join('\n'));
    },
    resolveId(id) { if (id === 'virtual:documentation') return '\0documentation'; },
    load(id) {
      if (id !== '\0documentation') return;
      const paths = [resolve(root, 'README.md'), ...walk(resolve(root, 'docs')), resolve(root, 'frontend/DESIGN.md')];
      const pages = paths.sort().map((path) => {
        this.addWatchFile(path);
        return { path: relative(root, path).replaceAll('\\', '/'), content: readFileSync(path, 'utf8') };
      });
      return `export default ${JSON.stringify(pages)}`;
    },
    handleHotUpdate({ file, server }) {
      if (file.endsWith('.md')) {
        const module = server.moduleGraph.getModuleById('\0documentation');
        if (module) server.moduleGraph.invalidateModule(module);
        server.ws.send({ type: 'full-reload' });
      }
    },
  };
}
