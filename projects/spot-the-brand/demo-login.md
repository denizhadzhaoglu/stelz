# Spot the Brand · Demo login

Een persistent demo-account waarmee je de volledige authenticated journey kunt doorlopen zonder STELZ aan te raken.

## Credentials

```
URL:      https://spotyourbrand.com/login.html
Email:    demo@spotyourbrand.com
Password: SpotTheDemo2026!
```

Of via de Vercel preview: `https://stelz-brand-watch.vercel.app/login.html`

## Wat zit erin

| | Demo brand | STELZ |
|---|---|---|
| Slug | `spot-the-brand-demo` | `stelz` |
| Role demo user | **Owner** | Read-only via public-demo |
| Public demo flag | Yes | Yes |
| Plan | Pro · €1.500/mo · `active` | Enterprise |
| Credits | 850 | 10.000 |
| Period end | +30 days from creation | 2027 |
| Creators | 20 (curated top-hitters, cloned from STELZ) | 545 |
| Content items | 596 | thousands |
| Positive detections | 754 | 436+ verified |
| Product lines | 4 (Original / Citrus / Berry / Zero) | 4 (STELZ real) |
| Hashtag pool | 5 (#demobrand, #demoweekend, etc.) | dozens |
| Pending invite | 1 visible (teammate@example.com) | — |

Het is een echte clone van een gecureerd subset van STELZ-data (de 20 creators met de meeste hits), met nieuwe UUIDs en `external_id` prefixed met `demo_` om collisions te voorkomen. Image storage paths zijn hergebruikt, dus de detection-thumbnails renderen identiek.

## De journey die je kunt doorlopen

1. **Login** → `/login.html` → sign in met de credentials hierboven.
2. **Dashboard** → `/?brand=spot-the-brand-demo` → 754 hits, 20 creators, 4 product lines.
3. **Account** → `/account.html?brand=spot-the-brand-demo`:
   - Subscription: Pro · Active · €1.500
   - Credits: 850 / 1.000
   - Team: jij als owner + 1 pending invite voor `teammate@example.com`
   - Notifications: daily summary aan, weekly PDF aan, Slack uit
   - Plan-change knop → echt naar Stripe Checkout (TEST mode)
   - Manage billing → naar Customer Portal (TEST mode)
   - Buy credits → top-up flow (TEST mode)
4. **Highlights** → `/highlights.html?brand=spot-the-brand-demo` → top 12 hits gecureerd.
5. **Story view** → `/story.html?brand=spot-the-brand-demo` → IG-stories swipe.
6. **Creator profile** → klik op een creator in de dashboard tabel → big hero + detection gallery + timeline + **"Generate DM drafts"** knop.

Brand switcher in header werkt: als demo user kun je `spot-the-brand-demo` zien (eigenaar) maar STELZ niet (geen brand_users membership). Anonymous visitors zien beide.

## Wat de demo user wel/niet mag

- **Edit demo brand**: alles. Brand profile, hashtags, product lines, team, notifications.
- **STELZ**: alleen lezen (via `?brand=stelz` of public landing). Geen write-toegang.
- **Stripe Checkout**: de "Change plan" + "Manage billing" + "Buy credits" knoppen werken echt en redirecten naar Stripe TEST mode. Geen echte betalingen mogelijk (TEST keys).
- **DM generator**: vereist Gemini key env var op de Edge Function (al gezet). Genereert 3 drafts per creator.

## Veiligheid

- Wachtwoord staat hierboven hardcoded. Niet voor publieke share. Voor sales-conversaties geef je liever individuele trial-accounts via de signup flow.
- Demo brand staat `is_public_demo=true` → anonymous viewers kunnen de dashboard URL openen zonder login. De login-flow is nodig voor: Account page, Team management, Notifications save, DM generator, plan changes.
- Als iemand iets sloopt aan de demo brand, kun je `re-seed` doen door dit script opnieuw te draaien (zie sectie hieronder).

## Re-seed / reset

Als de demo-data corrupted raakt of je wil opnieuw beginnen:

```sql
-- Wipe demo brand state (alleen die ene brand, STELZ wordt niet aangeraakt)
DELETE FROM detections WHERE brand_id = '147bcf2a-b4f2-40c6-8e1f-1152935f5836';
DELETE FROM content_images WHERE brand_id = '147bcf2a-b4f2-40c6-8e1f-1152935f5836';
DELETE FROM content_items WHERE brand_id = '147bcf2a-b4f2-40c6-8e1f-1152935f5836';
DELETE FROM creators WHERE brand_id = '147bcf2a-b4f2-40c6-8e1f-1152935f5836';
-- (brand, subscription, credits, team blijven staan)

-- Re-run the clone migrations from this session in order, or just:
-- ping me en ik draai het opnieuw.
```

## Toekomstig: meer demo users

Voor 1-on-1 demo's wil je per prospect een eigen tijdelijke account (zodat ze hun naam en email zien in de UI). Dat gaat het beste via de bestaande signup-flow met een korte trial. Deze hardcoded demo account is voor jouw eigen gebruik om de journey snel te doorlopen.

## Tech-details (voor archief)

- Auth user ID: `cf6ce632-86d5-4bca-bc6b-fc5c9dfb060e`
- Demo brand ID: `147bcf2a-b4f2-40c6-8e1f-1152935f5836`
- Aangemaakt op: 15 mei 2026
- Email confirmation: bypassed (admin API created with `email_confirm: true`)
- Plan ID gekoppeld: `pro` plan via `plans` table

Update gepaste fields hieronder als credentials wijzigen.
