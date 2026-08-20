// Paste-import — paste once, then the preview table IS the editor.
//
// The client's sheet is the starting point, not the truth: at least one handle
// in it was barely legible, so every cell (name, Instagram, TikTok) can be
// corrected by hand before anything is imported. Edited cells go through the
// exact same extractHandle validation as pasted ones (buildSelection), so what
// the footer counts is exactly what one addCreators call sends. Rows with a
// broken cell keep the raw pasted value visible — a creator that silently
// falls off a campaign roster is the worst possible failure mode.

import { useMemo, useState } from 'react'
import { Button, Textarea } from './ui'
import {
  buildSelection, extractHandle, parseCreatorList, toEditableRows, type EditableRow,
} from '../lib/importList'

type Row = EditableRow & { key: number }

let nextKey = 0
const withKeys = (rows: EditableRow[]): Row[] => rows.map((r) => ({ ...r, key: nextKey++ }))

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
  const [rows, setRows] = useState<Row[]>(() => withKeys(toEditableRows(parseCreatorList(initialText))))
  const [text, setText] = useState('')
  // With a pre-filled list the table leads; without one, pasting is step 1.
  const [showPaste, setShowPaste] = useState(rows.length === 0)

  const selection = useMemo(() => buildSelection(rows), [rows])
  const igCount = selection.creatorIds.filter((c) => c.startsWith('instagram_')).length
  const ttCount = selection.creatorIds.length - igCount

  const patchRow = (key: number, patch: Partial<EditableRow>) =>
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)))

  const applyPaste = () => {
    const parsed = parseCreatorList(text)
    if (parsed.rows.length === 0) return
    setRows(withKeys(toEditableRows(parsed)))
    setText('')
    setShowPaste(false)
  }

  return (
    <div className="space-y-4">
      {showPaste ? (
        <div className="space-y-2">
          <Textarea
            rows={8}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={placeholder}
            className="font-mono text-[12px]"
            spellCheck={false}
          />
          <div className="flex items-center gap-3">
            <Button size="sm" variant="secondary" disabled={!text.trim()} onClick={applyPaste}>
              {rows.length > 0 ? 'Vervang tabel door geplakte lijst' : 'Zet om naar tabel'}
            </Button>
            {rows.length > 0 && (
              <button
                onClick={() => setShowPaste(false)}
                className="text-[11px] text-[var(--color-ink-subtle)] hover:text-[var(--color-ink)] underline"
              >
                sluiten — tabel behouden
              </button>
            )}
          </div>
        </div>
      ) : (
        <button
          onClick={() => setShowPaste(true)}
          className="text-[11px] text-[var(--color-ink-subtle)] hover:text-[var(--color-ink)] underline"
        >
          Opnieuw plakken uit een sheet ▾
        </button>
      )}

      {rows.length > 0 && (
        <div className="border border-[var(--color-border)] max-h-96 overflow-y-auto">
          <table className="w-full text-[12px]">
            <thead className="sticky top-0 bg-[var(--color-bg)] z-10">
              <tr className="text-left text-[10px] uppercase tracking-widest text-[var(--color-ink-subtle)]">
                <th className="px-2 py-1.5 w-8"></th>
                <th className="px-2 py-1.5">Naam</th>
                <th className="px-2 py-1.5">Instagram</th>
                <th className="px-2 py-1.5">TikTok</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-border)]">
              {rows.map((row) => (
                <tr key={row.key} className={row.included ? '' : 'opacity-40'}>
                  <td className="px-2 py-1.5 align-top">
                    <input
                      type="checkbox"
                      checked={row.included}
                      onChange={() => patchRow(row.key, { included: !row.included })}
                    />
                  </td>
                  <td className="px-2 py-1 align-top">
                    <CellInput
                      value={row.name}
                      onChange={(v) => patchRow(row.key, { name: v })}
                      className="font-medium"
                    />
                  </td>
                  <td className="px-2 py-1 align-top">
                    <HandleCell
                      value={row.instagram}
                      platform="instagram"
                      onChange={(v) => patchRow(row.key, { instagram: v })}
                    />
                  </td>
                  <td className="px-2 py-1 align-top">
                    <HandleCell
                      value={row.tiktok}
                      platform="tiktok"
                      onChange={(v) => patchRow(row.key, { tiktok: v })}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {rows.length > 0 && (
        <button
          onClick={() => setRows((rs) => [...rs, ...withKeys([{ name: '', instagram: '', tiktok: '', included: true }])])}
          className="text-[11px] text-[var(--color-ink-subtle)] hover:text-[var(--color-ink)]"
        >
          + Rij toevoegen
        </button>
      )}

      {selection.warnings.length > 0 && (
        <ul className="text-[11px] text-[var(--color-warn)] space-y-0.5">
          {selection.warnings.map((w, i) => <li key={i}>⚠ {w}</li>)}
        </ul>
      )}

      <div className="flex items-center justify-between gap-3">
        <span className="text-[11px] text-[var(--color-ink-subtle)]">
          {selection.creatorIds.length} profielen geselecteerd ({igCount} Instagram, {ttCount} TikTok)
        </span>
        <Button
          variant="primary"
          size="sm"
          disabled={busy || selection.creatorIds.length === 0}
          onClick={() => onImport(selection.creatorIds, selection.names)}
        >
          {busy ? 'Bezig…' : submitLabel(selection.creatorIds.length)}
        </Button>
      </div>
    </div>
  )
}

function CellInput({
  value, onChange, className = '', invalid = false,
}: {
  value: string
  onChange: (v: string) => void
  className?: string
  invalid?: boolean
}) {
  return (
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      spellCheck={false}
      className={`w-full min-w-24 bg-transparent border-b py-0.5 text-[12px] focus:outline-none ${
        invalid
          ? 'border-[var(--color-warn)]'
          : 'border-transparent hover:border-[var(--color-border-strong)] focus:border-[var(--color-ink)]'
      } ${className}`}
    />
  )
}

function HandleCell({
  value, platform, onChange,
}: {
  value: string
  platform: 'instagram' | 'tiktok'
  onChange: (v: string) => void
}) {
  // Same validator as the parser and the final selection — a cell edit is a
  // fresh paste of one cell, nothing less strict.
  const { warning } = value.trim() ? extractHandle(value, platform) : { warning: null }
  return (
    <div>
      <CellInput value={value} onChange={onChange} invalid={warning != null} className="tabular-nums" />
      {warning && <div className="text-[10px] text-[var(--color-warn)] mt-0.5">{warning}</div>}
    </div>
  )
}
