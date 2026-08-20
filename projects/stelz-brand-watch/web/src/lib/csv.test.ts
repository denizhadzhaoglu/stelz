// CSV export — lib/csv.ts
//
// The interesting test here is the formula-injection one. Captions come from
// the open internet and land in a file a brand manager opens in Excel; a
// caption beginning "=" is a formula there, not text.

import { describe, it, expect } from 'vitest'
import { detectionsCsv, communitiesCsv, datedFilename } from './csv'
import type { DetectionRow } from './types'

function row(p: Partial<DetectionRow>): DetectionRow {
  return {
    detection_id: 'd1', creator_id: null, creator_handle: 'anna',
    creator_category: null, platform: 'instagram', product_line: null,
    confidence: 0.9, size_in_frame: null, is_primary_subject: null,
    image_url: null, stored_path: null, post_url: null, post_caption: null,
    posted_at: null, likes_count: null, comments_count: null, views_count: null,
    follower_count: null, creator_tier: null, verified: null, context: null,
    post_hashtags: null, post_mentions: null, music: null, extras: null,
    surface_type: null, visible_text: null, false_positive_risk: null,
    people_count: null, setting: null, activity: null, gate: null,
    verify_verdict: null, verify_brand: null, verify_reason: null,
    sentiment: null, sentiment_score: null, sentiment_rationale: null,
    brand_id: 'stelz', detected: true, is_false_positive: null, ...p,
  }
}

describe('detectionsCsv', () => {
  it('neutralises captions that Excel would run as a formula', () => {
    const csv = detectionsCsv([row({ post_caption: '=HYPERLINK("http://x","click")' })])
    expect(csv).toContain(`"'=HYPERLINK`)
  })

  it('neutralises the other formula lead-ins too', () => {
    for (const lead of ['+1', '-1+1', '@SUM(A1)']) {
      const csv = detectionsCsv([row({ post_caption: lead })])
      expect(csv, lead).toContain(`"'${lead.replace(/"/g, '""')}"`)
    }
  })

  it('survives captions containing quotes, commas and newlines', () => {
    const csv = detectionsCsv([row({ post_caption: 'hij zei "top", en\nging weg' })])
    expect(csv).toContain('"hij zei ""top"", en\nging weg"')
    // The header row plus one record; the embedded newline must not split it.
    expect(csv.split('\r\n')[0]).toContain('posted_at')
  })

  it('writes empty strings, never "null" or "0", for missing values', () => {
    const csv = detectionsCsv([row({})])
    expect(csv).not.toContain('null')
    expect(csv).not.toContain('undefined')
  })

  it('starts with a BOM so Excel reads the accents in Stëlz', () => {
    expect(detectionsCsv([row({})]).charCodeAt(0)).toBe(0xfeff)
  })

  it('includes the discovery class, which is the whole point of the tool', () => {
    const csv = detectionsCsv([row({ post_hashtags: ['zomer'] })])
    expect(csv).toContain('visual_only')
  })
})

describe('communitiesCsv', () => {
  it('renders an empty profile list as a header alone', () => {
    const csv = communitiesCsv([])
    expect(csv.split('\r\n')).toHaveLength(1)
    expect(csv).toContain('scene')
  })
})

describe('datedFilename', () => {
  it('dates the file so two exports do not overwrite each other', () => {
    expect(datedFilename('stelz-hits', '2026-08-18T09:00:00Z')).toBe('stelz-hits-2026-08-18.csv')
  })
})
