import { defineConfig } from 'vite';
import { documentationPlugin } from './docs-plugin.js';

// The docs build is served under /docs/ on the app's hostname (wrangler.toml), so its assets live there too.
export default defineConfig(({ mode }) => ({
  base: mode === 'docs' ? '/docs/' : '/',
  plugins: [documentationPlugin()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
        ws: true,
      },
    },
  },
}));
