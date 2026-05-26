# OAuth Provider Setup — Google + Meta + Instagram

UI staat klaar op `/signup.html` en `/login.html`. Voor productie moeten de providers nog gekoppeld worden in Supabase dashboard plus credentials van Google en Meta.

## 1. Google OAuth (15 min)

### Google Cloud Console
1. Open https://console.cloud.google.com/
2. Maak nieuw project: `Lens Brand Watch`
3. Ga naar **APIs & Services → OAuth consent screen**
   - User Type: External
   - App name: `Lens`
   - User support email: hello@jackandai.com
   - Authorized domains: `vercel.app`, `supabase.co`, `jackandai.com`
   - Developer contact: jouw email
4. Scopes: `email`, `profile`, `openid`
5. Ga naar **Credentials → Create Credentials → OAuth Client ID**
   - Application type: Web application
   - Name: `Lens Supabase`
   - Authorized redirect URIs:
     ```
     https://menaatbeoeutywulcdvv.supabase.co/auth/v1/callback
     ```
6. Kopieer **Client ID** en **Client Secret**

### Supabase Dashboard
1. Open https://supabase.com/dashboard/project/menaatbeoeutywulcdvv/auth/providers
2. Toggle **Google** aan
3. Plak Client ID + Client Secret
4. Save

Klaar. Test via https://stelz-brand-watch.vercel.app/signup.html → Continue with Google.

## 2. Meta (Facebook) OAuth (20 min)

### Meta for Developers
1. Open https://developers.facebook.com/apps
2. Create App
   - Type: **Consumer**
   - Display name: `Lens Brand Watch`
   - Contact email: hello@jackandai.com
3. Dashboard → **Add Product → Facebook Login → Set Up**
4. In Facebook Login settings → **Valid OAuth Redirect URIs**:
   ```
   https://menaatbeoeutywulcdvv.supabase.co/auth/v1/callback
   ```
5. **Settings → Basic**:
   - App Domains: `vercel.app`, `supabase.co`
   - Privacy Policy URL: jouw privacy URL (zie hieronder)
   - Terms of Service URL: jouw terms URL
   - Category: Business and Pages
6. Maak app **Live** (uit Development)
7. Kopieer **App ID** en **App Secret**

### Supabase Dashboard
1. Auth → Providers → Toggle **Facebook** aan
2. Plak App ID + App Secret
3. Save

## 3. Instagram Login (premium, niet aanbevolen voor MVP)

Instagram Login werkt anders dan Meta Login:
- Vereist **Meta Business verificatie** (kan weken duren)
- Vereist Instagram Business of Creator account verbinding bij gebruiker
- Andere scopes (`instagram_basic`, `instagram_content_publish`)
- Aparte App Review nodig met use case demonstration

Aanbeveling: skip voor MVP, gebruik **Continue with Meta** als equivalent. Instagram Login alleen toevoegen als we Instagram-specifieke content management willen aanbieden (cross-posting, advanced insights, etc).

## 4. Privacy + Terms URLs (verplicht voor OAuth approval)

Beide providers vereisen public URLs:
- Privacy Policy URL: https://stelz-brand-watch.vercel.app/privacy.html (TODO: deze pagina maken)
- Terms of Service URL: https://stelz-brand-watch.vercel.app/terms.html (TODO: maken)

Templates voor beide: https://app.termly.io of https://www.iubenda.com (~€5-25/mo).
Content moet beschrijven:
- Welke data we verzamelen (email, OAuth ID, optionally connected social handles)
- Hoe we het gebruiken (auth, brand association, billing)
- Hoe gebruikers data kunnen wissen (right to deletion via support)
- Cookies/tracking

## 5. Email confirmation flow (Supabase Auth)

Supabase stuurt automatisch confirm email bij signup. Configureer in:
- **Auth → Email Templates → Confirm signup**
- Subject: `Bevestig je Lens account`
- Body: branded HTML met JackandAI styling
- Reply-to: hello@jackandai.com

Voor productie SMTP: Resend.com (free tier 100/dag), SendGrid, of Postmark. Anders gebruikt Supabase eigen mail server met fair use limit.

## 6. RLS policies aanzetten (CRITICAL voor multi-tenant)

Zodra OAuth live is:

```sql
-- Voorbeeld policy: users zien alleen hun eigen brand
alter table creators enable row level security;
create policy "Users see their brand creators"
  on creators for select
  using (
    brand_id in (
      select brand_id from brand_users where user_id = auth.uid()
    )
  );
```

Toepassen op: `creators`, `content_items`, `content_images`, `detections`, `discovery_runs`, `discovery_queue`, `backfill_jobs`, `reports`, `credit_balances`, `credit_transactions`, `subscriptions`.

`brands` zelf is publiek toegankelijk (voor branding info).

## Tijdslijn

- Dag 1: Google OAuth setup + test
- Dag 2: Meta OAuth setup + test
- Dag 3: Privacy/Terms pages (template-based)
- Dag 4: RLS policies + multi-tenant routing
- Dag 5: User-brand binding flow na OAuth signin

Zonder OAuth setup werkt het email/password fallback wel via Supabase Auth — getest in `/signup.html`.
