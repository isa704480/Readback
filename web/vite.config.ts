import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // The server agent is building against :8000. Proxying in dev means the
    // client can use same-origin paths and never needs CORS configured on a
    // backend that is still being written.
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/health': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
  build: {
    target: 'es2022',
    /* Not in the published bundle. Vercel serves whatever lands in dist/, and a
       .map carries `sourcesContent` -- the full TypeScript, comments included,
       which in this repository means the reasoning behind every gate, written
       out for anyone who opens devtools. A build that wants them asks:
       `npx vite build --sourcemap`. */
    sourcemap: false,
  },
});
