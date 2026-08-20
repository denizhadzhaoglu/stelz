// The paste-import parser is the gate between a client spreadsheet and a
// tracked (billed) creator roster — every shape a real sheet throws at it is
// pinned here, plus a pre-flight over the actual Lowlands seed so a
// transcription typo fails CI instead of a live import.
import { describe, expect, it } from 'vitest'
import { buildSelection, extractHandle, parseCreatorList, toEditableRows } from './importList'
import { LOWLANDS_SEED } from '../data/lowlandsSeed'
import { splitCreatorId } from './projects'

describe('extractHandle', () => {
  it('extracts from an instagram URL with tracking junk and trailing slash', () => {
    expect(extractHandle('https://www.instagram.com/frankslotta/?hl=Elize%20K', 'instagram'))
      .toEqual({ handle: 'frankslotta', warning: null })
    expect(extractHandle('http://instagram.com/rvdofficial/?hl=nl', 'instagram'))
      .toEqual({ handle: 'rvdofficial', warning: null })
  })

  it('extracts from a tiktok URL with a query string', () => {
    expect(extractHandle('https://www.tiktok.com/@pleun.bierbooms?lang=nl', 'tiktok'))
      .toEqual({ handle: 'pleun.bierbooms', warning: null })
  })

  it('accepts bare and @-prefixed handles, lowercasing them', () => {
    expect(extractHandle('joshbram_', 'instagram').handle).toBe('joshbram_')
    expect(extractHandle('@Booijagency', 'tiktok').handle).toBe('booijagency')
  })

  it('treats absence markers as absent, without warning', () => {
    for (const marker of ['', ' ', '-', 'Geen', 'geen', 'n.v.t.', 'nvt']) {
      expect(extractHandle(marker, 'tiktok')).toEqual({ handle: null, warning: null })
    }
  })

  it('warns on content links instead of importing "p" as a creator', () => {
    const out = extractHandle('https://www.instagram.com/p/abc123/', 'instagram')
    expect(out.handle).toBeNull()
    expect(out.warning).toMatch(/post/)
  })

  it('warns on cross-platform links in the wrong column', () => {
    expect(extractHandle('https://www.tiktok.com/@x', 'instagram').warning).toMatch(/TikTok/)
    expect(extractHandle('https://www.instagram.com/x/', 'tiktok').warning).toMatch(/Instagram/)
  })

  it('warns on garbage instead of guessing', () => {
    const out = extractHandle('niet een handle!', 'instagram')
    expect(out.handle).toBeNull()
    expect(out.warning).toMatch(/geen geldige/)
  })
})

describe('parseCreatorList', () => {
  it('parses a TSV block into rows, ids and a names map', () => {
    const out = parseCreatorList(
      'Anna A.\thttps://www.instagram.com/anna/\thttps://www.tiktok.com/@anna\n' +
      'Bob B.\tbob_b\tGeen',
    )
    expect(out.rows).toHaveLength(2)
    expect(out.creatorIds).toEqual(['instagram_anna', 'tiktok_anna', 'instagram_bob_b'])
    expect(out.names).toEqual({
      instagram_anna: 'Anna A.',
      tiktok_anna: 'Anna A.',
      instagram_bob_b: 'Bob B.',
    })
    expect(out.warnings).toEqual([])
  })

  it('skips the header row of a real sheet', () => {
    const out = parseCreatorList('Gasten\tTag Instagram\tTag TikTok\nAnna\tanna\tGeen')
    expect(out.rows).toHaveLength(1)
    expect(out.creatorIds).toEqual(['instagram_anna'])
  })

  it('handles CRLF input and CSV/semicolon fallbacks', () => {
    expect(parseCreatorList('Anna,anna,Geen\r\nBob,bob,Geen').creatorIds)
      .toEqual(['instagram_anna', 'instagram_bob'])
    expect(parseCreatorList('Anna;anna;Geen').creatorIds).toEqual(['instagram_anna'])
  })

  it('keeps a TikTok-only person', () => {
    const out = parseCreatorList('Solo\tGeen\ttiktok_only_person')
    expect(out.creatorIds).toEqual(['tiktok_tiktok_only_person'])
  })

  it('round-trips underscore handles through splitCreatorId', () => {
    // Composite ids split on the FIRST underscore — a handle full of
    // underscores must survive the trip intact.
    const out = parseCreatorList('Jort\tjort_runia\tGeen')
    expect(splitCreatorId(out.creatorIds[0])).toEqual({ platform: 'instagram', handle: 'jort_runia' })
  })

  it('dedupes repeated handles with a warning naming the line', () => {
    const out = parseCreatorList('Anna\tanna\tGeen\nAnna 2\tanna\tGeen')
    expect(out.creatorIds).toEqual(['instagram_anna'])
    expect(out.warnings.some((w) => w.includes('instagram_anna'))).toBe(true)
    // First occurrence owns the display name.
    expect(out.names.instagram_anna).toBe('Anna')
  })

  it('surfaces unparseable cells as row warnings, never silent drops', () => {
    const out = parseCreatorList('Anna\thttps://www.instagram.com/p/xyz/\tGeen')
    expect(out.rows[0].creatorIds).toEqual([])
    expect(out.rows[0].warnings).toHaveLength(1)
  })
})

describe('editable-table helpers', () => {
  it('toEditableRows keeps handles, empties absent cells, keeps raw junk to fix', () => {
    const rows = toEditableRows(parseCreatorList(
      'Anna\thttps://www.instagram.com/anna/\tGeen\n' +
      'Broken\thttps://www.instagram.com/p/xyz/\t@broken',
    ))
    expect(rows[0]).toEqual({ name: 'Anna', instagram: 'anna', tiktok: '', included: true })
    // The unparseable cell survives verbatim so the user sees what to fix.
    expect(rows[1].instagram).toBe('https://www.instagram.com/p/xyz/')
    expect(rows[1].tiktok).toBe('broken')
  })

  it('buildSelection re-validates edited cells like a fresh paste', () => {
    const out = buildSelection([
      { name: 'Rein van Duivenboden', instagram: 'rvdofficial', tiktok: '@ReinVD', included: true },
      { name: 'Uitgezet', instagram: 'weg', tiktok: '', included: false },
      { name: 'Kapot', instagram: 'niet geldig!', tiktok: '', included: true },
    ])
    expect(out.creatorIds).toEqual(['instagram_rvdofficial', 'tiktok_reinvd'])
    expect(out.names).toEqual({
      instagram_rvdofficial: 'Rein van Duivenboden',
      tiktok_reinvd: 'Rein van Duivenboden',
    })
    // Excluded rows contribute nothing; broken cells warn instead of vanishing.
    expect(out.warnings).toHaveLength(1)
    expect(out.warnings[0]).toMatch(/rij 3/)
  })

  it('buildSelection dedupes across rows with a warning', () => {
    const out = buildSelection([
      { name: 'A', instagram: 'anna', tiktok: '', included: true },
      { name: 'B', instagram: 'anna', tiktok: '', included: true },
    ])
    expect(out.creatorIds).toEqual(['instagram_anna'])
    expect(out.warnings[0]).toMatch(/dubbele/)
    expect(out.names.instagram_anna).toBe('A')
  })

  it('the seed round-trips through the editable table unchanged', () => {
    const out = buildSelection(toEditableRows(parseCreatorList(LOWLANDS_SEED)))
    expect(out.creatorIds).toHaveLength(53)
    expect(out.warnings).toEqual([])
    expect(Object.keys(out.names)).toHaveLength(53)
  })
})

describe('LOWLANDS_SEED pre-flight', () => {
  it('parses clean: 28 people, 53 platform ids, zero warnings', () => {
    const out = parseCreatorList(LOWLANDS_SEED)
    expect(out.rows).toHaveLength(28)
    expect(out.creatorIds).toHaveLength(53)
    expect(out.creatorIds.filter((c) => c.startsWith('instagram_'))).toHaveLength(28)
    expect(out.creatorIds.filter((c) => c.startsWith('tiktok_'))).toHaveLength(25)
    expect(out.warnings).toEqual([])
    expect(out.rows.every((r) => r.warnings.length === 0)).toBe(true)
    // Every id carries a display name for the roster view.
    expect(Object.keys(out.names)).toHaveLength(53)
  })
})
