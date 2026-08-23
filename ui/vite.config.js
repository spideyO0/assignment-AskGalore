import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API is a separate process (`coa-mapper serve`). Proxying /api keeps the
// browser on one origin, so no CORS in the loop and the same relative paths work
// whether the UI is served by Vite in dev or from any static host in production.
export default defineConfig({
  plugins: [react()],
  server: {
    // Bind IPv4 explicitly. Vite's default host is 'localhost', which Node 17+
    // resolves to ::1 first, so the dev server ends up listening on [::1] only
    // and every IPv4 client — curl 127.0.0.1, some corporate proxies, most
    // container port-forwards — gets ECONNREFUSED against a server that is
    // demonstrably running.
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: process.env.COA_API ?? 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
    },
  },
})
