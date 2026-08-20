// Paste-import parser for creator lists — the "Gasten / Tag Instagram /
// Tag TikTok" spreadsheets a client sends before a campaign. Pure and
// framework-free so the preview table, the seed's pre-flight test and the
// actual import all run the exact same code: what the user approves in the
// preview is literally what gets imported.
//
// Column contract: [name, instagram, tiktok]. Handles may be bare, @-prefixed
// or full profile URLs; "Geen"/"-"/empty mark an absent platform without
// complaint. Anything unparseable becomes a row warning, never a silent drop —
// a roster import that quietly loses a creator is worse than one that asks.

export type ImportRow = {
  line: number
  name: string | null
  instagram: string | null
  tiktok: string | null
  creatorIds: string[]
  warnings: string[]
}

export type ParsedImport = {
  rows: ImportRow[]
  creatorIds: string[]
  names: Record<string, string>
  warnings: string[]
}

// Markers a spreadsheet uses for "this person is not on that platform".
const ABSENT = new Set(['', '-', '–', '—', 'geen', 'nvt', 'n.v.t.', 'none', 'n/a'])

// Instagram/TikTok handle charset. Both platforms are stricter than this in
// places, but anything outside it is certainly wrong.
const HANDLE_RE = /^[a-z0-9._]{1,30}$/

// instagram.com path heads that are content links, not profiles.
const IG_NON_PROFILE = new Set(['p', 'reel', 'reels', 'stories', 'explore', 'tv', 'accounts'])

export function extractHandle(
  raw: string,
  platform: 'instagram' | 'tiktok',
): { handle: string | null; warning: string | null } {
  // Zero-width characters ride along with copy-paste from Sheets.
  const cleaned = raw.replace(/[​‌‍﻿]/g, '').trim()
  if (ABSENT.has(cleaned.toLowerCase())) return { handle: null, warning: null }

  let candidate = cleaned
  if (platform === 'instagram') {
    const m = cleaned.match(/instagram\.com\/([^/?#\s]+)/i)
    if (m) {
      const seg = decodeSafe(m[1])
      if (IG_NON_PROFILE.has(seg.toLowerCase())) {
        return { handle: null, warning: `"${truncate(cleaned)}" is een post/story-link, geen profiel` }
      }
      candidate = seg
    } else if (/tiktok\.com/i.test(cleaned)) {
      return { handle: null, warning: `TikTok-link in de Instagram-kolom: "${truncate(cleaned)}"` }
    }
  } else {
    const m = cleaned.match(/tiktok\.com\/@([^/?#\s]+)/i)
    if (m) {
      candidate = decodeSafe(m[1])
    } else if (/tiktok\.com/i.test(cleaned)) {
      return { handle: null, warning: `TikTok-link zonder @handle: "${truncate(cleaned)}"` }
    } else if (/instagram\.com/i.test(cleaned)) {
      return { handle: null, warning: `Instagram-link in de TikTok-kolom: "${truncate(cleaned)}"` }
    }
  }

  const handle = candidate.replace(/^@/, '').replace(/\/+$/, '').toLowerCase()
  if (!HANDLE_RE.test(handle)) {
    return { handle: null, warning: `geen geldige ${platform}-handle: "${truncate(cleaned)}"` }
  }
  return { handle, warning: null }
}

export function parseCreatorList(text: string): ParsedImport {
  const rows: ImportRow[] = []
  const creatorIds: string[] = []
  const names: Record<string, string> = {}
  const warnings: string[] = []
  const seen = new Set<string>()

  const lines = text.split(/\r?\n/)
  let sawContent = false

  const HEADER_CELL = /^(gasten|naam|name|creator|tag\s+instagram|tag\s+tiktok|instagram|tiktok|ig|tt|handle|url|link)$/i

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (!line.trim()) continue

    const delim = line.includes('\t') ? '\t' : line.includes(';') ? ';' : ','
    const cells = line.split(delim).map((c) => c.trim())

    // Header heuristic: the first content line whose every cell is a column
    // LABEL ("Gasten", "Tag Instagram") rather than data. Cell-exact on
    // purpose — a handle merely containing "tiktok" must not look like one.
    if (!sawContent && cells.some((c) => c !== '') && cells.every((c) => c === '' || HEADER_CELL.test(c))) {
      sawContent = true
      continue
    }
    sawContent = true
    if (cells.length < 2) {
      warnings.push(`regel ${i + 1} overgeslagen — geen kolommen gevonden: "${truncate(line)}"`)
      continue
    }

    const name = cells[0] ? cells[0].slice(0, 120) : null
    const ig = extractHandle(cells[1] ?? '', 'instagram')
    const tt = extractHandle(cells[2] ?? '', 'tiktok')

    const row: ImportRow = {
      line: i + 1,
      name,
      instagram: ig.handle,
      tiktok: tt.handle,
      creatorIds: [],
      warnings: [ig.warning, tt.warning].filter((w): w is string => w != null),
    }

    for (const [platform, handle] of [['instagram', ig.handle], ['tiktok', tt.handle]] as const) {
      if (!handle) continue
      const cid = `${platform}_${handle}`
      if (seen.has(cid)) {
        warnings.push(`dubbele handle overgeslagen op regel ${i + 1}: ${cid}`)
        continue
      }
      seen.add(cid)
      row.creatorIds.push(cid)
      creatorIds.push(cid)
      if (name) names[cid] = name
    }

    if (row.creatorIds.length === 0 && row.warnings.length === 0) {
      row.warnings.push('geen handles op deze regel')
    }
    rows.push(row)
  }

  return { rows, creatorIds, names, warnings }
}

function decodeSafe(s: string): string {
  try {
    return decodeURIComponent(s)
  } catch {
    return s
  }
}

function truncate(s: string, n = 60): string {
  return s.length > n ? `${s.slice(0, n)}…` : s
}
