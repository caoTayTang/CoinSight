import { defineConfig } from 'vite';
import { documentationPlugin } from './docs-plugin.js';

export default defineConfig({
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
});
