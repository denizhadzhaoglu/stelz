// Paste-import — textarea → parsed preview → one bulk add.
//
// The preview table is the contract: what the user sees checked is exactly
// what one addCreators call sends (the parser is pure and shared with the
// seed's pre-flight test). Rows with unparseable cells surface their warning
// inline instead of being silently dropped — for a campaign roster, a creator
// that quietly falls off the list is the worst possible failure mode.

import { useMemo, useState } from 'react'
import { Button, Textarea } from './ui'
import { parseCreatorList } from '../lib/importList'

export function PasteImport({
  initialText = '',
  busy,
  submitLabel,
  onImport,
  placeholder = 'Naam\tInstagram-link of handle\tTikTok-link of handle',
}: {
  initialText?: string
  busy: boolean
  submitLabel: (n: number) => string
  onImport: (creatorIds: string[], names: Record<string, string>) => void
  placeholder?: string
}) {
  const [text, setText] = useState(initialText)
  const [excluded, setExcluded] = useState<Set<number>>(new Set())

  const parsed = useMemo(() => parseCreatorList(text), [text])

  const selectedIds: string[] = []
  const selectedNames: Record<string, string> = {}
  let igCount = 0
  let ttCount = 0
  for (const row of parsed.rows) {
    if (excluded.has(row.line)) continue
    for (const cid of row.creatorIds) {
      selectedIds.push(cid)
      if (parsed.names[cid]) selectedNames[cid] = parsed.names[cid]
      if (cid.startsWith('instagram_')) igCount++
      else ttCount++
    }
  }

  const toggleRow = (line: number) => {
    setExcluded((prev) => {
      const next = new Set(prev)
      if (next.has(line)) next.delete(line)
      else next.add(line)
      return next
    })
  }

  return (
    <div className="space-y-4">
      <Textarea
        rows={8}
        value={text}
        onChange={(e) => { setText(e.target.value); setExcluded(new Set()) }}
        placeholder={placeholder}
        className="font-mono text-[12px]"
        spellCheck={false}
      />

      {parsed.warnings.length > 0 && (
        <ul className="text-[11px] text-[var(--color-warn)] space-y-0.5">
          {parsed.warnings.map((w, i) => <li key={i}>⚠ {w}</li>)}
        </ul>
      )}

      {parsed.rows.length > 0 && (
        <div className="border border-[var(--color-border)] max-h-80 overflow-y-auto">
          <table className="w-full text-[12px]">
            <thead className="sticky top-0 bg-[var(--color-bg)]">
              <tr className="text-left text-[10px] uppercase tracking-widest text-[var(--color-ink-subtle)]">
                <th className="px-2 py-1.5 w-8"></th>
                <th className="px-2 py-1.5">Naam</th>
                <th className="px-2 py-1.5">Instagram</th>
                <th className="px-2 py-1.5">TikTok</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-border)]">
              {parsed.rows.map((row) => (
                <tr key={row.line} className={excluded.has(row.line) ? 'opacity-40' : ''}>
                  <td className="px-2 py-1.5">
                    <input
                      type="checkbox"
                      checked={!excluded.has(row.line)}
                      disabled={row.creatorIds.length === 0}
                      onChange={() => toggleRow(row.line)}
                    />
                  </td>
                  <td className="px-2 py-1.5 font-medium">{row.name ?? '—'}</td>
                  <td className="px-2 py-1.5 tabular-nums">{row.instagram ? `@${row.instagram}` : '—'}</td>
                  <td className="px-2 py-1.5 tabular-nums">
                    {row.tiktok ? `@${row.tiktok}` : '—'}
                    {row.warnings.length > 0 && (
                      <span className="block text-[10px] text-[var(--color-warn)]">{row.warnings.join(' · ')}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center justify-between gap-3">
        <span className="text-[11px] text-[var(--color-ink-subtle)]">
          {selectedIds.length} creators geselecteerd ({igCount} Instagram, {ttCount} TikTok)
        </span>
        <Button
          variant="primary"
          size="sm"
          disabled={busy || selectedIds.length === 0}
          onClick={() => onImport(selectedIds, selectedNames)}
        >
          {busy ? 'Bezig…' : submitLabel(selectedIds.length)}
        </Button>
      </div>
    </div>
  )
}
