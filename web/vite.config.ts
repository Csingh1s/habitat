import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig(({ mode, isPreview }) => ({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: mode === 'development' && !isPreview ? {
      '/api': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
        headers: {
          'X-Dev-Tenant-Id': 'demo-tenant',
          'X-Dev-User-Id': 'demo-inspector',
        },
      },
    } : undefined,
  },
}))
