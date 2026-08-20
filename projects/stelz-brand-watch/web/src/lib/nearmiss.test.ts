// Near-miss brand tags — lib/signal.ts
//
// Reported from a demo: a card showed "NO TAG" next to a visible #steltz chip.
// The classification was right — a brand searching #stelz genuinely will not
// find #steltz — but the label was unreadable next to the evidence, which is
// its own kind of wrong.
//
// The risk in fixing it is over-matching: a five-letter brand name is one edit
// away from a lot of ordinary Dutch. These tests fence that in.

import { describe, it, expect } from 'vitest'
import { nearMissBrandTag, classifySignal, isBrandTag } from './signal'

describe('nearMissBrandTag', () => {
  it('catches the misspelling that started this', () => {
    expect(nearMissBrandTag('steltz')).toBe('steltz')
    expect(nearMissBrandTag('#Steltz')).toBe('steltz')
  })

  it('catches other single-slip spellings', () => {
    for (const t of ['stlez', 'stelsz', 'stels']) {
      expect(nearMissBrandTag(t), t).toBeTruthy()
    }
  })

  it('leaves the misspellings that already count as brand tags alone', () => {
    // #stelzz starts with the brand name, so isBrandTag already accepts it and
    // the post is "tagged", not a discovery. Flagging it as a near miss would
    // contradict the badge the card is about to show.
    expect(isBrandTag('stelzz')).toBe(true)
    expect(nearMissBrandTag('stelzz')).toBeNull()
  })

  it('stays silent on tags that are already correct', () => {
    // These are real brand tags; the card should say "tagged", not "misspelled".
    expect(nearMissBrandTag('stelz')).toBeNull()
    expect(nearMissBrandTag('drinkstelz')).toBeNull()
    expect(isBrandTag('stelz')).toBe(true)
  })

  it('does not fire on unrelated words from the same posts', () => {
    for (const t of ['ijs', 'maddeys', 'nix18', 'blikkendag', 'zomer', 'feest', 'stad']) {
      expect(nearMissBrandTag(t), t).toBeNull()
    }
  })

  it('refuses short tags, where one edit means almost nothing', () => {
    expect(nearMissBrandTag('stel')).toBeNull()
    expect(nearMissBrandTag('telz')).toBeNull()
  })

  it('refuses long tags, where one edit is a coincidence', () => {
    expect(nearMissBrandTag('stelzhardseltzer')).toBeNull()
  })
})

describe('classifySignal with a misspelled tag', () => {
  const post = {
    creator_handle: 'lynnkranenb',
    post_caption: 'Dubbel B# steltz',
    post_hashtags: ['nix18', 'steltz', 'blikkendag'],
    post_mentions: [],
  } as never

  it('still counts as a discovery — the claim we sell is unchanged', () => {
    // This is the point of the whole product. Searching #stelz does not surface
    // #steltz, so the brand could not have found this post themselves.
    const s = classifySignal(post)
    expect(s.signal).toBe('visual_only')
    expect(s.findable).toBe(false)
  })

  it('reports which tag was the near miss, so the card can say so', () => {
    expect(classifySignal(post).misspelledTag).toBe('steltz')
  })

  it('reports null when the post really carries no brand-ish tag', () => {
    const s = classifySignal({
      creator_handle: 'someone', post_caption: 'lekker weekend',
      post_hashtags: ['zomer', 'vrijmibo'], post_mentions: [],
    } as never)
    expect(s.signal).toBe('visual_only')
    expect(s.misspelledTag).toBeNull()
  })

  it('a correctly tagged post is not a near miss', () => {
    const s = classifySignal({
      creator_handle: 'someone', post_caption: '', post_hashtags: ['stelz'], post_mentions: [],
    } as never)
    expect(s.signal).toBe('hashtag')
    expect(s.misspelledTag).toBeNull()
  })
})
