import { svelte } from '@sveltejs/vite-plugin-svelte'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [svelte()],
  server: {
    host: true,
    allowedHosts: true,
    proxy: { '/api': `http://127.0.0.1:${process.env.API_PORT ?? 8799}` },
  },
  build: { chunkSizeWarningLimit: 1200 },
})
