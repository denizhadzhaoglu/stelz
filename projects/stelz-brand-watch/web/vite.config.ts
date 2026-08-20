import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import fs from 'node:fs'
import path from 'node:path'

/**
 * Serves the story preview — the fixtures and the archived media — on the dev
 * server and NOWHERE ELSE.
 *
 * Why a middleware and not files in public/: everything in public/ is copied
 * verbatim into dist/, so `vite build && firebase deploy --only hosting` would
 * publish it. That already happened to the two fixture JSONs — 230 kB of
 * scraped Instagram data, including signed CDN URLs, sitting on public hosting
 * because they had to live somewhere the dev server could reach. Media would
 * have been worse: 118 MB of other people's photographs.
 *
 * `apply: 'serve'` plus `configureServer` means this code path does not exist
 * in a build at all — a stronger guarantee than the DEV checks in
 * lib/devPreview.ts, which depend on the minifier folding them away.
 *
 * Produced by tools/stelz_brand_watch/61_stories_preview_fixture.py and
 * 62_stories_archive.py. Nothing here = 404 = the UI stays on live data.
 */
function storyPreview() {
  const archive = path.resolve(__dirname, '../../../.tmp/stories-archive')
  const TYPES: Record<string, string> = {
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
    '.webp': 'image/webp', '.mp4': 'video/mp4', '.json': 'application/json',
  }
  const FIXTURES = new Set(['/preview-stories.json', '/preview-story-posts.json'])

  function send(res: any, file: string, ext: string) {
    if (!TYPES[ext] || !fs.existsSync(file)) {
      res.statusCode = 404
      return res.end('not found')
    }
    res.setHeader('Content-Type', TYPES[ext])
    res.setHeader('Cache-Control', 'no-store')
    fs.createReadStream(file).pipe(res)
  }

  return {
    name: 'stelz-story-preview',
    apply: 'serve' as const,
    configureServer(server: { middlewares: { use: (fn: (req: any, res: any, next: () => void) => void) => void } }) {
      server.middlewares.use((req, res, next) => {
        const url: string = (req.url || '').split('?')[0]
        if (FIXTURES.has(url)) {
          return send(res, path.join(archive, path.basename(url)), '.json')
        }
        if (!url.startsWith('/preview-media/')) return next()
        // basename only: a request for ../../.env must not escape the archive.
        const name = path.basename(decodeURIComponent(url))
        return send(res, path.join(archive, 'media', name), path.extname(name).toLowerCase())
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss(), storyPreview()],
  server: { port: 5173, host: true },
})
