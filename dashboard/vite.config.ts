import fs from 'node:fs';
import path from 'node:path';
import react from '@vitejs/plugin-react';
import type { Plugin } from 'vite';
import { defineConfig } from 'vitest/config';

/**
 * Makes the built page work when opened straight from disk (file://): browsers refuse module
 * scripts there, so the bundle is a classic script and the `crossorigin` attributes are removed.
 */
function classicScript(): Plugin {
  return {
    name: 'driftpilot-classic-script',
    enforce: 'post',
    transformIndexHtml(html) {
      return html.replace(/<script type="module" crossorigin/g, '<script defer').replace(/ crossorigin/g, '');
    },
  };
}

/** In `npm run dev`, serve /data.json from dev-data/ (made by `npm run demo-data`). */
function devData(): Plugin {
  return {
    name: 'driftpilot-dev-data',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use('/data.json', (_req, res) => {
        const file = path.resolve(__dirname, 'dev-data/data.json');
        if (!fs.existsSync(file)) {
          res.statusCode = 404;
          res.end('run `npm run demo-data` first');
          return;
        }
        res.setHeader('content-type', 'application/json');
        res.end(fs.readFileSync(file));
      });
    },
  };
}

export default defineConfig({
  base: './',
  plugins: [react(), classicScript(), devData()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    modulePreload: false,
    cssCodeSplit: false,
    chunkSizeWarningLimit: 900,
    rollupOptions: { output: { format: 'iife', inlineDynamicImports: true } },
  },
  test: { environment: 'node', include: ['tests/**/*.test.ts'] },
});
