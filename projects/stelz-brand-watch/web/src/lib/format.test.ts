import { describe, expect, it } from 'vitest'
import { compactNum, fmtDate, fmtNum, timeAgo } from './format'

describe('fmtNum', () => {
  it('groups thousands the Dutch way', () => {
    // The whole point: a browser-locale default printed "1,284" for the client.
    expect(fmtNum(1284)).toBe('1.284')
    expect(fmtNum(1_284_000)).toBe('1.284.000')
    expect(fmtNum(42)).toBe('42')
  })

  it('renders nothing-values as a dash instead of NaN', () => {
    expect(fmtNum(null)).toBe('—')
    expect(fmtNum(undefined)).toBe('—')
    expect(fmtNum(Number.NaN)).toBe('—')
  })
})

describe('compactNum', () => {
  it('uses a decimal comma, not a point', () => {
    expect(compactNum(1200)).toBe('1,2k')
    expect(compactNum(1_200_000)).toBe('1,2M')
  })

  it('drops a trailing zero decimal', () => {
    expect(compactNum(1000)).toBe('1k')
    expect(compactNum(2_000_000)).toBe('2M')
  })

  it('leaves small numbers alone', () => {
    expect(compactNum(999)).toBe('999')
    expect(compactNum(0)).toBe('0')
  })
})

describe('fmtDate', () => {
  const now = new Date('2026-08-20T12:00:00Z')

  it('omits the year within the current year', () => {
    expect(fmtDate('2026-08-20T09:00:00Z', now)).toMatch(/20 aug/)
  })

  it('includes the year for other years', () => {
    expect(fmtDate('2025-12-31T09:00:00Z', now)).toMatch(/2025/)
  })

  it('survives junk input', () => {
    expect(fmtDate(null, now)).toBe('—')
    expect(fmtDate('not-a-date', now)).toBe('—')
  })
})

describe('timeAgo', () => {
  const now = Date.parse('2026-08-20T12:00:00Z')

  it('counts up through the units', () => {
    expect(timeAgo('2026-08-20T11:59:40Z', now)).toBe('nu')
    expect(timeAgo('2026-08-20T11:45:00Z', now)).toBe('15 min')
    expect(timeAgo('2026-08-20T07:00:00Z', now)).toBe('5 u')
    expect(timeAgo('2026-08-18T12:00:00Z', now)).toBe('2 d')
  })

  it('falls back to a date once relative age stops being useful', () => {
    expect(timeAgo('2026-07-01T12:00:00Z', now)).toMatch(/jul/)
  })
})
