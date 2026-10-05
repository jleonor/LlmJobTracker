import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const API_TARGET = 'http://127.0.0.1:8765'
const TOKEN_HEADER = 'X-Launch-Token'

// https://vite.dev/config/
export default defineConfig(({ command }) => {
  // The launch token stays on the dev server. The browser calls /api/* and the proxy adds the header.
  const launchToken = process.env.LJT_TOKEN ?? ''
  if (command === 'serve' && !launchToken) {
    console.warn('LJT_TOKEN is not set, so /api calls will be rejected. Start with: python scripts/dev.py')
  }

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': path.resolve(import.meta.dirname, './src'),
      },
    },
    server: {
      host: '127.0.0.1',
      proxy: {
        '/api': {
          target: API_TARGET,
          rewrite: (urlPath) => urlPath.replace(/^\/api/, ''),
          configure: (proxy) => {
            proxy.on('proxyReq', (proxyReq) => {
              proxyReq.setHeader(TOKEN_HEADER, launchToken)
            })
          },
        },
      },
    },
  }
})
