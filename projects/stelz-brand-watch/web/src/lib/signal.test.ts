// Tests for the discovery-value classifier.
//
// Why these matter more than they look: the whole dashboard now DEFAULTS to
// showing only `visual_only` rows. A classifier bug in the "too many brand
// tags" direction silently hides genuine untagged content — the exact problem
// this module was built to fix, in reverse. And the Stelzlager class of bug has
// already shipped once in this codebase; firebase/functions/tests/
// test_identity.py exists because of it.

import { describe, expect, it } from 'vitest'
import { classifySignal, isBrandTag, normalize, signalCounts, untaggedShare } from './signal'
import type { SignalInput } from './signal'
import { dedupeByPost } from './types'
import type { DetectionRow } from './types'

const row = (p: Partial<SignalInput> = {}): SignalInput => ({
  creator_handle: 'someone',
  post_hashtags: [],
  post_mentions: [],
  post_caption: '',
  ...p,
})

describe('normalize', () => {
  it('strips diacritics and lowercases', () => {
    expect(normalize('STËLZ')).toBe('stelz')
    expect(normalize('Stélz')).toBe('stelz')
  })
  it('handles empty input', () => {
    expect(normalize(null)).toBe('')
    expect(normalize(undefined)).toBe('')
  })
})

describe('isBrandTag', () => {
  it('matches the core brand tags', () => {
    for (const t of ['stelz', 'drinkstelz', 'stelzhardseltzer', 'casastelz', 'teamstelz'])
      expect(isBrandTag(t), t).toBe(true)
  })

  it('matches accented and hashed forms', () => {
    expect(isBrandTag('#Stëlz')).toBe(true)
    expect(isBrandTag('STELZ')).toBe(true)
  })

  // THE ORDERING TEST. #stelzlime and #stelzlemon are real flavour tags whose
  // prefix collides with the stelzlager/stelzen denylist family. If the
  // denylist ever runs before the allowlist, these break.
  it('matches flavour tags that collide with the denylist family', () => {
    expect(isBrandTag('stelzlime')).toBe(true)
    expect(isBrandTag('stelzlemon')).toBe(true)
  })

  // The German regression that removed OCR from the detection pipeline.
  it('rejects the Stelzlager family', () => {
    for (const t of ['stelzlager', 'stelzlagern', 'stelzer', 'stelzl', 'stelzvogel'])
      expect(isBrandTag(t), t).toBe(false)
  })

  // Dutch stilt-walking compounds that exact-token matching would miss.
  it('rejects stelzen-prefixed compounds', () => {
    for (const t of ['stelzen', 'stelzenlopen', 'stelzenlopers', 'stelzenlaufer'])
      expect(isBrandTag(t), t).toBe(false)
  })

  it('matches unknown stelz-prefixed tags via the catch-all', () => {
    expect(isBrandTag('stelzweekend')).toBe(true)
    expect(isBrandTag('stelz2026')).toBe(true)
  })

  it('rejects unrelated lifestyle tags', () => {
    for (const t of ['vrijmibo', 'huisfeest', 'koningsdag', 'festivalseizoen', ''])
      expect(isBrandTag(t), t).toBe(false)
  })

  // Prefix, not substring — a fan account tag must not be swallowed.
  it('does not match tags that merely contain the brand mid-word', () => {
    expect(isBrandTag('ilovestelz')).toBe(false)
  })
})

describe('classifySignal', () => {
  it('flags a brand hashtag as findable', () => {
    const r = classifySignal(row({ post_hashtags: ['vrijmibo', 'stelz'] }))
    expect(r.signal).toBe('hashtag')
    expect(r.findable).toBe(true)
    expect(r.matched).toEqual(['stelz'])
  })

  it('treats a post with only lifestyle tags as untagged', () => {
    const r = classifySignal(row({ post_hashtags: ['vrijmibo', 'huisfeest'] }))
    expect(r.signal).toBe('visual_only')
    expect(r.findable).toBe(false)
  })

  it('treats a post with no tags at all as untagged', () => {
    expect(classifySignal(row()).signal).toBe('visual_only')
  })

  // scan_hashtags.py:825 writes mentions raw-case, unlike hashtags.
  it('matches raw-case @mentions', () => {
    const r = classifySignal(row({ post_mentions: ['@DrinkStelz'] }))
    expect(r.signal).toBe('mention')
    expect(r.findable).toBe(true)
  })

  it('ignores mentions of non-brand accounts', () => {
    expect(classifySignal(row({ post_mentions: ['@somefriend'] })).signal).toBe('visual_only')
  })

  it('flags brand-owned accounts', () => {
    expect(classifySignal(row({ creator_handle: 'drinkstelz' })).signal).toBe('brand_owned')
    expect(classifySignal(row({ creator_handle: 'bavaria.bierkoerier' })).signal).toBe('brand_owned')
  })

  it('gives brand_owned precedence over hashtag', () => {
    const r = classifySignal(row({ creator_handle: 'drinkstelz', post_hashtags: ['stelz'] }))
    expect(r.signal).toBe('brand_owned')
  })

  it('does not treat a fan account as brand-owned', () => {
    expect(classifySignal(row({ creator_handle: 'stelzlover' })).signal).toBe('visual_only')
  })

  // The deliberate divergence from the legacy Python classifier: a caption
  // mention does NOT make a post findable, because Instagram has no caption
  // search and post_caption is truncated to 500 chars anyway.
  it('keeps a caption-only brand mention untagged, but flags it for display', () => {
    const r = classifySignal(row({ post_caption: 'lekker glaasje STËLZ in de zon' }))
    expect(r.signal).toBe('visual_only')
    expect(r.findable).toBe(false)
    expect(r.namedInCaption).toBe(true)
  })

  it('does not flag Stelzlager prose as a caption mention', () => {
    const r = classifySignal(row({ post_caption: 'Stelzlager gemonteerd vandaag' }))
    expect(r.signal).toBe('visual_only')
    expect(r.namedInCaption).toBe(false)
  })

  // lib/tiktok_scraper.py:66 hardcodes hashtags: [], so tags can live only in
  // the caption. This rescue can only ever move a post untagged -> tagged.
  it('rescues hashtags from the caption when the array is empty', () => {
    const r = classifySignal(row({ post_hashtags: [], post_caption: 'feestje #stelz #vrijmibo' }))
    expect(r.signal).toBe('hashtag')
  })

  it('does not use the caption rescue when the array is populated', () => {
    const r = classifySignal(row({ post_hashtags: ['vrijmibo'], post_caption: 'zie #stelz' }))
    expect(r.signal).toBe('visual_only')
  })

  it('survives null arrays from legacy docs', () => {
    const r = classifySignal({
      creator_handle: 'x',
      post_hashtags: null as unknown as string[],
      post_mentions: null as unknown as string[],
      post_caption: null as unknown as string,
    })
    expect(r.signal).toBe('visual_only')
  })
})

describe('aggregates', () => {
  const rows = [
    { post_hashtags: ['stelz'] },
    { post_hashtags: ['vrijmibo'] },
    { post_hashtags: ['huisfeest'] },
    { post_hashtags: [], post_mentions: ['@drinkstelz'] },
    { creator_handle: 'drinkstelz' },
  ].map((p) => row(p)) as unknown as DetectionRow[]

  it('counts each class', () => {
    const c = signalCounts(rows)
    expect(c).toEqual({ visual_only: 2, hashtag: 1, mention: 1, brand_owned: 1 })
  })

  it('excludes brand-owned posts from the untagged denominator', () => {
    const s = untaggedShare(rows)
    expect(s.total).toBe(4)          // not 5 — the brand's own post is excluded
    expect(s.untagged).toBe(2)
    expect(s.pct).toBe(50)
  })

  it('does not divide by zero on an empty set', () => {
    expect(untaggedShare([]).pct).toBe(0)
  })
})

// The carousel bug this fix exists for: scan_hashtags._persist_sidecar_child
// writes `hashtags` for carousel children but NOT `mentions`, and dedupeByPost
// used to inherit whichever slide won on confidence. So a post's "untagged"
// verdict depended on which slide the model liked best.
describe('dedupeByPost + classification stability', () => {
  const base = {
    detection_id: 'instagram_111_0',
    post_id: 'instagram_111_0',
    creator_handle: 'fan',
    platform: 'instagram',
    detected: true,
    posted_at: '2026-08-01T10:00:00Z',
    post_caption: '',
  } as unknown as DetectionRow

  it('unions mentions across carousel slides regardless of which scores highest', () => {
    const slides = [
      { ...base, detection_id: 'instagram_111_0', post_id: 'instagram_111_0', confidence: 0.95, post_hashtags: [], post_mentions: [] },
      { ...base, detection_id: 'instagram_111_1', post_id: 'instagram_111_1', confidence: 0.70, post_hashtags: [], post_mentions: ['@drinkstelz'] },
    ] as unknown as DetectionRow[]

    // Proves this test is not vacuous: the slide that WINS on confidence has
    // no mention of its own, so pre-fix behaviour (inherit the winner wholesale)
    // classified this post as an untagged discovery.
    expect(classifySignal(slides[0]).signal).toBe('visual_only')

    const merged = dedupeByPost(slides)
    expect(merged).toHaveLength(1)
    expect(merged[0].confidence).toBe(0.95)   // the winner is still representative
    expect(classifySignal(merged[0]).signal).toBe('mention')
  })

  it('unions hashtags across slides', () => {
    const slides = [
      { ...base, detection_id: 'instagram_222_0', post_id: 'instagram_222_0', confidence: 0.9, post_hashtags: ['vrijmibo'], post_mentions: [] },
      { ...base, detection_id: 'instagram_222_1', post_id: 'instagram_222_1', confidence: 0.6, post_hashtags: ['stelz'], post_mentions: [] },
    ] as unknown as DetectionRow[]
    expect(classifySignal(dedupeByPost(slides)[0]).signal).toBe('hashtag')
  })

  it('leaves a genuinely untagged post untagged', () => {
    const slides = [
      { ...base, detection_id: 'instagram_333_0', post_id: 'instagram_333_0', confidence: 0.9, post_hashtags: ['vrijmibo'], post_mentions: [] },
      { ...base, detection_id: 'instagram_333_1', post_id: 'instagram_333_1', confidence: 0.6, post_hashtags: ['huisfeest'], post_mentions: [] },
    ] as unknown as DetectionRow[]
    expect(classifySignal(dedupeByPost(slides)[0]).signal).toBe('visual_only')
  })
})
