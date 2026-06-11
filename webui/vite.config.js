import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import { readFileSync } from 'fs'

/**
 * Read the server port from claude_rag.toml.
 * Falls back to claude_rag.toml.example, then the built-in default (8765).
 */
function getServerPort() {
  const tomlPaths = [
    resolve(__dirname, '../claude_rag.toml'),
    resolve(__dirname, '../claude_rag.toml.example'),
  ]
  for (const path of tomlPaths) {
    try {
      const text = readFileSync(path, 'utf-8')
      // Simple TOML section parser: find [server] block, then match port = <number>
      const sec = text.match(/\[server\]([\s\S]*?)(?=\n\[|$)/)
      if (sec) {
        const port = sec[1].match(/^\s*port\s*=\s*(\d+)/m)
        if (port) return parseInt(port[1], 10)
      }
    } catch (_) { /* file not found or unreadable — try next */ }
  }
  return 8765 // built-in default
}

const SERVER_PORT = getServerPort()

export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: resolve(__dirname, '../src/server/static'),
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': `http://localhost:${SERVER_PORT}`,
    },
  },
})
