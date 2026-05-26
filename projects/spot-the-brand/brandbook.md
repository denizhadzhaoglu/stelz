# Spot the Brand · Brandbook v0.2

A SaaS product brand by JackandAI. This is what Spot the Brand is, what it believes, what it sounds like, and what it looks like.

Read [`manifesto.md`](manifesto.md) first. The manifesto is the WHY. This document is the HOW.

---

## 1. Positioning

### One-liner
We see what your social tool misses.

### Three-liner
Brand monitoring built on computer vision. We find every visible mention of your product in social content, not just the ones with a hashtag. Built for challenger brands. Daily scans, AI-verified, ready for action.

### Twenty-second pitch (memorize this)
> Most brand monitoring tools read text — hashtags, mentions, captions. But people don't write about brands anymore, they show them. We use computer vision to find your product in the actual image. Eighty percent of the moments your current tool misses, we catch. Daily. Automatically. Five hundred euros a month.

### What we are NOT
- We are not an influencer marketing platform. (Tagger, Modash do that.)
- We are not a social listening tool for sentiment. (Brandwatch, Talkwalker do that.)
- We are not an outreach CRM. (Klear, Aspire do that.)

We are **visual brand monitoring**. New category. We own it because it didn't exist yet.

### Who we serve
Challenger brands with visually distinctive products and consumer-facing social. Roughly:
- €1M–€100M revenue range
- Marketing team of 2-30 people
- Active social presence
- Has tried Storyclash / Brand24 / similar and felt the gap
- Marketing budget €100k–€2M annually
- Often Dutch / Belgian / Northern European first, expanding

We are deliberately not built for enterprise giants in v1. They come later.

---

## 2. Voice

We sound like a sharp technical operator who happens to know marketing — not the other way around.

### Voice attributes (with anti-patterns)

| We sound | We don't sound |
|----------|----------------|
| Direct | Polite |
| Confident, evidence-led | Boastful |
| Slightly nerdy | Trying-too-hard-cool |
| Plain | Jargony |
| Specific | Aspirational |
| Anti-legacy-tooling | Anti-anyone-personally |
| Honest about limits | Falsely humble |

### Sentence-level rules
- Short sentences over long ones. Trade fluency for clarity.
- No em-dashes ever. Use commas, colons, periods.
- No "revolutionize", "synergy", "next-gen", "unleash", "game-changer", "AI-powered".
- No exclamation points outside of celebratory contexts (a customer milestone, never marketing copy).
- Numbers earn the right to appear. Vague claims don't.
- Active voice. "We see" not "products are seen by us".
- Cite the limit when you cite the win. "Daily scans, with a 4-hour latency on TikTok" beats "real-time scans".

### Sample copy

#### What lands
- "Your brand is in more posts than you think."
- "We see the can. They read the caption."
- "Eighty percent of your social mentions don't have a hashtag. We find them anyway."
- "Brand monitoring built for the way people actually post in 2026."
- "Computer vision finally works for this. We're the first to apply it to brand monitoring."

#### What doesn't (rewrite these if you see them)
- "Unleash the power of AI for your brand" → "We use computer vision to find your brand in posts."
- "Take your social listening to the next level" → "Most social listening misses 80% of mentions. We find them."
- "Spot the Brand revolutionizes brand monitoring" → "Spot the Brand is the first vision-native brand monitoring tool."

### Speaking about competitors

When a competitor comes up:
- Name them factually if it's relevant.
- Describe the gap, not the people. "Storyclash is great at hashtag-based discovery. They don't do visual detection — that's where we live."
- Don't trash. The marketing teams using Storyclash today are our future customers. They picked the best tool that existed when they bought it. We're the better tool now.

### Speaking about ourselves

We have one customer publicly using us in production: STELZ, a Dutch hard seltzer brand. Reference them when proof is needed. Don't over-anchor on them. Spot the Brand is not "the STELZ tool". STELZ is one of many.

When we don't yet have a relevant customer story, say so:
> "We're early. Our first reference customer is in hard seltzer. The exact pattern applies to your category, but I'd be transparent that we're a young company."

That honesty beats inventing case studies.

---

## 3. Visual identity

### 3.1 Colors

| Role | Name | Hex | Use |
|------|------|-----|-----|
| Background | Black | `#0A0A0A` | Default canvas. Dark mode is the standard, light mode is the exception. |
| Surface | Charcoal | `#141414` | Cards, panels, modal interiors. |
| Border | Graphite | `#2A2A2A` | Subtle dividers, card outlines. |
| Primary accent | Spot Red | `#FF1300` | The detection signal. Brand mark accent. Primary CTAs. The period after "Brand". |
| Text primary | Off-white | `#EDEDED` | Body text on dark. |
| Text muted | Slate | `#888888` | Labels, secondary text. |
| Success | Detect Green | `#4ADE80` | Verified/OK states. |
| Warning | Tier-1 Gold | `#FBBF24` | Tier-1 creator badges, premium states. |

Red is reserved. It carries meaning — "we found it" / "act on this". Never use red for decoration.

### 3.2 Typography

| Role | Family | Notes |
|------|--------|-------|
| Display | Benzin (JackandAI house) | Headlines, hero copy. `letter-spacing: -0.02em` |
| UI / body | TT Hoves Pro | All product chrome and reading text |
| Data / accents | JetBrains Mono | Coordinates, confidence values, timestamps, "DETECTED · 0.94" |

Rules:
- Display never below 24px.
- Numbers always with `font-variant-numeric: tabular-nums`.
- Monospace SPARINGLY. It's a flavor, not a base.

### 3.3 The signature device

A **red dashed bounding box** with a monospace label `DETECTED · 0.94` at top-left.

This is the brand's central visual idea. It comes from how computer vision models display what they've found. We wear it as identity.

Use it:
- Around products in our content
- Around the wordmark in the hero lockup
- As decoration on hero images, OG cards, slide title pages
- Animated in reels: the box snaps in, the label types

Don't use it:
- For purely decorative purposes with no detection context
- Around faces (privacy + creep)
- As a generic frame for unrelated content

### 3.4 Logo system

The wordmark: `Spot the Brand.` lowercase + small caps. The period is always red.

Five working variants in [`logo-concepts.svg`](logo-concepts.svg):
1. Wordmark only (default UI)
2. Boxed wordmark with `DETECTED · 0.99` label (hero / sales / slide titles)
3. App icon: red square + white bounding-box outline (favicon, social profile pic)
4. Horizontal compact: icon + wordmark side by side (email signatures, footers)
5. Stamp monogram: "S" inside boxed cell (optional social profile pic)

Lockups in practice:

| Surface | Variant |
|---------|---------|
| Web header | Wordmark only |
| Social profile pic | App icon |
| Slide title page | Boxed wordmark |
| Email signature | Horizontal compact |
| Favicon | Red square |
| OG/share card | Boxed wordmark variant |

What never:
- Don't change the period color (it's always red)
- Don't drop the period
- Don't pair with a competing logo at equal size
- Don't stretch the wordmark
- Don't place wordmark on busy backgrounds without a dark or light scrim

### 3.5 Motifs and accents

- **Crosshair**: thin red horizontal + vertical line meeting in the middle of the canvas, with a 6-12px red dot at the intersection. Use at low opacity as background texture on hero pages.
- **Scan circles**: 2-3 concentric red rings at the crosshair intersection, all at low opacity. "We're focused on this point."
- **Confidence pills**: small red rounded rectangles with white monospace number ("0.94"). Decorate detected products.
- **Coordinate readouts**: small `x:240 y:380` style overlays in mono, low opacity, on hero imagery. Adds technical authenticity.
- **The scan line**: animated red gradient that traverses the canvas (4-6 sec loop). Video only.

Use motifs sparingly. One per surface is enough. Three is decoration overload.

### 3.6 Photography rules

- Real, slightly-imperfect lifestyle imagery. Phone-camera grain is OK. Studio-perfect feels wrong.
- Products in hands, on shelves, in environments. Never floating on white seamless.
- When the photo features a brand product, overlay our bounding-box treatment.
- For hero imagery showing creators: ASK PERMISSION before publishing. Default: anonymize or use generated/internal photos.
- Black bars top/bottom on reels (~5% each) for the surveillance-feed feel.
- Never use stock photography. Either real, real-permissioned, or generated.

---

## 4. The product brand vs the customers we serve

Spot the Brand is the brand. STELZ, Vandestreek, and the rest are customers. Don't conflate.

When demoing or telling stories, the structure is:

> "Spot the Brand works like this. [10 sec product explanation.]
> One example: a Dutch hard seltzer customer of ours, STELZ, has tracked 436 visual product mentions in the last quarter, 86% of which had no hashtag. That kind of result is what the product enables for any brand with a visually distinctive product."

NOT:

> "Look at STELZ's dashboard. This is what you get."

The first centers the brand. The second centers the customer. The first scales. The second doesn't.

Use customer examples as PROOF, not as identity.

---

## 5. Component library

Already established in code at `projects/stelz-brand-watch/dashboard/`. Reuse for future product surfaces.

- **Card**: `background: #141414`, `border: 1px solid #2A2A2A`, `border-radius: 12px`, `padding: 20-26px`
- **Pill**: `padding: 2px 8px`, `border-radius: 999px`, `font-size: 11px`, optionally colored border for status
- **Button primary**: `background: #FF1300`, `color: white`, `padding: 10px 18px`, `border-radius: 8px`
- **Button ghost**: `background: transparent`, `border: 1px solid #2A2A2A`, `color: #EDEDED`
- **Empty state**: `border: 1px dashed #2A2A2A`, `padding: 40px`, `text-align: center`, muted gray text

---

## 6. Brand-level message hierarchy

When deciding what to communicate, this is the priority order:

1. **The category insight** (we see what others miss; brands live visually)
2. **The capability** (computer vision for brand monitoring, daily, automated)
3. **The proof** (here's what we found for a real customer; the magnitude)
4. **The product** (dashboard, alerts, reports, team seats)
5. **The price** (€500 starter, €1.500 pro, custom enterprise)

Lead with 1. Cover 2 and 3 in every prospect conversation. Get to 4 only when there's interest. Quote 5 last.

In ads / social: lead with 1 plus a hook from 3.
On landing: 1 + 2 + 3 above the fold, 4 + 5 below.
In demo: 1 + 2 first 90 seconds, 3 + 4 next 6 minutes, 5 in the last minute.

---

## 7. Brand-safe message templates

### For social posts
- "We see what your social tool misses."
- "Your brand is in more posts than you think."
- "Hashtag tracking is 2015. Visual detection is what comes next."
- "Eighty percent of your social mentions have no caption. We catch them anyway."

### For sales emails (cold)
- "Most brand monitoring is blind to most brand mentions. We've measured 80%+ blind-spot on the brands we've tested. Want to see your number?"

### For PR / press
- "Spot the Brand is the first vision-native brand monitoring platform. Vision models matured in 2024-2025; we're applying them to a category that's been text-only for a decade."

### For investors
- "Earned-media intelligence at the speed and cost of search. €500/month per brand. Built for the 10.000 challenger brands in EU + UK who can't afford Storyclash. €15k MRR target by Q3 2026."

### For hiring
- "We're building computer-vision-native brand monitoring. Sharp small team at JackandAI. Direct work, no politics, big upside."

---

## 8. Brand promise / claims we can defend

| Claim | Evidence |
|-------|----------|
| Computer vision detects ~80% of mentions that text-based tools miss | Measured on STELZ over 90 days: 436 visual hits, ~60 caption-tagged. Expect similar for any brand with a distinctive product. |
| Daily scans complete in under 30 minutes per brand | Current pipeline benchmark on Railway. Holds at 5-10x scale. |
| <5% false positive rate after Pro verification | STELZ Pro-verified set: documented. Improves with brand-specific reference packs. |
| First hits surface within 24-48h of activation | Initial scan queued on signup; first detections within first daily scan cycle. |

Don't claim things we haven't measured. When measurement isn't there yet, say "we expect" not "we deliver".

---

## 9. Tone in adversity

When things break (and they will):
- Admit it directly. "Our scanner went down for 4 hours this morning. Here's what we did. Here's what we changed so it won't repeat."
- Don't blame the platform / API / scraper / weather.
- Quantify the impact, quantify the fix.
- Offer concrete remediation if appropriate (a credit refund, a make-good).

Tone: technical operator who knows things break, owns the outcome.

---

## 10. Decisions still open

- [ ] Trademark "Spot the Brand" via BMM/WIPO (€350, 10 min)
- [ ] Register defensive `.ai` / `.io` domains
- [ ] Commission a real designer for v1.0 logo refinement (current is functional, not refined)
- [ ] Lock the "by JackandAI" lockup convention (always present? only in launch period? phased out?)

Owner: Meinte + Lukas. Review every 4 weeks until v1.0 of brandbook ships.
