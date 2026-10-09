import { readFileSync, readdirSync } from 'node:fs';
import { resolve, relative } from 'node:path';

// Explicit public documentation roots. Never walk credentials, data or dependencies.
export function documentationPlugin() {
  const root = resolve(import.meta.dirname, '..');
  const walk = (dir) => readdirSync(dir, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory() ? walk(resolve(dir, entry.name)) : entry.name.endsWith('.md') ? [resolve(dir, entry.name)] : []);
  return {
    name: 'coinsight-documentation',
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
