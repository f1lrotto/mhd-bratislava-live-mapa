import { svelte } from '@sveltejs/vite-plugin-svelte'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { defineConfig, type Plugin } from 'vite'

// Emits sw.js with the build's JS and CSS to precache; the hashed names version its cache.
function serviceWorker(): Plugin {
  return {
    name: 'service-worker',
    apply: 'build',
    generateBundle(_, bundle) {
      const files = Object.keys(bundle)
        .filter((f) => /\.(js|mjs|css)$/.test(f))
        .sort()
        .map((f) => `/${f}`)
      const version = createHash('sha256').update(files.join('\n')).digest('hex').slice(0, 12)
      const source = readFileSync(new URL('sw.js', import.meta.url), 'utf8').replace(
        'self.__PRECACHE__',
        JSON.stringify({ version, files }),
      )
      this.emitFile({ type: 'asset', fileName: 'sw.js', source })
    },
  }
}

export default defineConfig({
  plugins: [svelte(), serviceWorker()],
  server: {
    host: true,
    allowedHosts: true,
    // The browser's host and scheme reach the API: the accounts server checks requests' origin against them.
    proxy: { '/api': { target: `http://127.0.0.1:${process.env.API_PORT ?? 8799}`, changeOrigin: false } },
  },
  build: { chunkSizeWarningLimit: 1200 },
})
