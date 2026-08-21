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
  const tmp = path.resolve(__dirname, '../../../.tmp')
  const EVENTS_TMP = path.join(tmp, 'events')
  const EVENTS_DIR = path.resolve(__dirname, 'src/data/events')
  // The one event whose stories fixture 61_stories_preview_fixture.py writes.
  const STORIES = path.join(EVENTS_TMP, 'lowlands-2026', 'stories')
  const TYPES: Record<string, string> = {
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
    '.webp': 'image/webp', '.mp4': 'video/mp4', '.json': 'application/json',
  }
  // Where each fixture lives. Explicit map, not a path join on user input:
  // this middleware answers requests from a browser, and "serve whatever the
  // URL names" is how a dev server ends up handing out .env.
  const FIXTURES: Record<string, string> = {
    '/preview-stories.json': path.join(STORIES, 'preview-stories.json'),
    '/preview-story-posts.json': path.join(STORIES, 'preview-story-posts.json'),
    '/preview-campaign.json': path.join(tmp, 'preview-campaign.json'),
    '/preview-campaign-detections.json': path.join(tmp, 'preview-campaign-detections.json'),
  }
  // Media lives at .tmp/events/<event>/<kind>/media/<file>, so a URL now names
  // TWO directories instead of one. Both are checked against an allow-list by
  // exact membership, never by prefix: this middleware turns URL segments into
  // a filesystem path, and the whole point is that no segment outside these
  // sets can ever become one.
  //
  // The event list is read from the definitions directory at startup rather
  // than hard-coded, so adding an event does not mean remembering to edit a
  // second list — but it is still a fixed set computed here, not the segment
  // the browser sent.
  const EVENT_IDS = new Set<string>(
    fs.existsSync(EVENTS_DIR)
      ? fs.readdirSync(EVENTS_DIR).filter((f) => f.endsWith('.json'))
          .map((f) => path.basename(f, '.json'))
      : [],
  )
  const KINDS = new Set(['stories', 'ig-posts', 'tiktok', 'discovery'])

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
        const fixture = FIXTURES[url]
        if (fixture) return send(res, fixture, '.json')
        if (!url.startsWith('/preview-media/')) return next()

        // /preview-media/<event>/<kind>/<file>, or /preview-media/<file> for
        // the stories archive of the default event.
        const parts = decodeURIComponent(url)
          .slice('/preview-media/'.length)
          .split('/')
          .filter(Boolean)
        // basename on every segment: a raw or encoded ../../.env must not
        // escape, and neither must an event or kind that is not on a list.
        const name = path.basename(parts[parts.length - 1] ?? '')
        const [ev, kind] = [path.basename(parts[0] ?? ''), path.basename(parts[1] ?? '')]
        const dir = parts.length > 2 && EVENT_IDS.has(ev) && KINDS.has(kind)
          ? path.join(EVENTS_TMP, ev, kind, 'media')
          : parts.length === 1
            ? path.join(STORIES, 'media')
            : null
        // An unrecognised event or kind is a 404, not a fallback to the stories
        // archive: silently serving a different directory than the URL asked
        // for is how an allow-list stops being one.
        if (!dir) {
          res.statusCode = 404
          return res.end('not found')
        }
        return send(res, path.join(dir, name), path.extname(name).toLowerCase())
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss(), storyPreview()],
  server: { port: 5173, host: true },
})
